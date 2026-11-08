import asyncio
from pathlib import Path
import sys
import unittest
from scripts.media_upload_relay import handle, pac, parse_target


class TargetTests(unittest.TestCase):
    def test_exact_allowed_tls_authority_only(self):
        targets = {'media.example.test': 23451}
        self.assertEqual(parse_target('MEDIA.example.test:443', targets), 'media.example.test')
        for value in ('media.example.test:80', 'other.example.test:443',
                      'media.example.test.evil.test:443', 'u@media.example.test:443',
                      'media.example.test:443/path', '127.0.0.1:443', '[::1]:443',
                      'media.example.test.:443', 'media.example.test:443\r\n'):
            self.assertIsNone(parse_target(value, targets))

    def test_pac_has_exact_hosts_and_direct_fallback(self):
        body = pac({'media.example.test': 23451}, 23450).decode()
        self.assertIn('["media.example.test"]', body)
        self.assertIn('hosts.indexOf(host.toLowerCase()) >= 0', body)
        self.assertIn('PROXY 127.0.0.1:23450', body)
        self.assertIn('return "DIRECT"', body)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        self.upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.targets = {'media.example.test': self.upstream.sockets[0].getsockname()[1]}
        self.relay = await asyncio.start_server(
            lambda r, w: handle(r, w, self.targets, 23450), '127.0.0.1', 0)
        self.port = self.relay.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        for server in (self.relay, self.upstream):
            server.close()
            await server.wait_closed()

    async def request(self, head):
        r, w = await asyncio.open_connection('127.0.0.1', self.port)
        w.write(head)
        await w.drain()
        return r, w

    async def test_tunnels_opaque_bytes_without_parsing_them(self):
        r, w = await self.request(b'CONNECT media.example.test:443 HTTP/1.1\r\n\r\n')
        self.assertIn(b'200 Connection Established', await r.readuntil(b'\r\n\r\n'))
        opaque = bytes(range(256)) * 32
        w.write(opaque)
        await w.drain()
        self.assertEqual(await r.readexactly(len(opaque)), opaque)
        w.close()
        await w.wait_closed()

    async def test_unknown_targets_denied(self):
        r, w = await self.request(b'CONNECT localhost:22 HTTP/1.1\r\n\r\n')
        self.assertIn(b'403 Forbidden', await r.read())
        w.close()
        await w.wait_closed()

    async def test_pac_available_without_exposing_other_paths(self):
        r, w = await self.request(b'GET /douyin-upload.pac HTTP/1.1\r\n\r\n')
        self.assertIn(b'FindProxyForURL', await r.read())
        w.close()
        await w.wait_closed()

    async def test_forbidden_methods_paths_and_ports(self):
        for head in (
            b'GET /private HTTP/1.1\r\n\r\n',
            b'POST /douyin-upload.pac HTTP/1.1\r\n\r\n',
            b'CONNECT media.example.test:22 HTTP/1.1\r\n\r\n',
            b'CONNECT media.example.test:443 HTTP/1.0\r\n\r\n',
            b'CONNECT media.example.test.evil.test:443 HTTP/1.1\r\n\r\n',
        ):
            with self.subTest(head=head):
                r, w = await self.request(head)
                self.assertIn(b'403 Forbidden', await r.read())
                w.close()
                await w.wait_closed()

    async def test_parallel_media_connections_do_not_exhaust_relay(self):
        # Chromium can retain six connections per media host, plus requests
        # to additional upload hosts. The old eight-slot relay dropped these.
        reservation = await asyncio.start_server(lambda r, w: w.close(), '127.0.0.1', 0)
        port = reservation.sockets[0].getsockname()[1]
        reservation.close()
        await reservation.wait_closed()
        script = Path(__file__).resolve().parents[1] / 'scripts/media_upload_relay.py'
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(script), '--port', str(port),
            '--upstream', f'media.example.test={self.targets["media.example.test"]}',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        clients = []
        try:
            self.assertIn(b'listening', await asyncio.wait_for(process.stdout.readline(), 5))
            for index in range(32):
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                clients.append(writer)
                writer.write(b'CONNECT media.example.test:443 HTTP/1.1\r\n\r\n')
                await writer.drain()
                response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
                self.assertIn(b'200 Connection Established', response)
                payload = f'opaque-{index}'.encode()
                writer.write(payload)
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)), 3), payload)
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            clients.append(writer)
            self.assertIn(b'503 Service Unavailable', await asyncio.wait_for(reader.read(), 3))
        finally:
            for writer in clients:
                writer.close()
                await writer.wait_closed()
            if process.returncode is None:
                process.terminate()
            await asyncio.wait_for(process.wait(), 5)


if __name__ == '__main__':
    unittest.main()
