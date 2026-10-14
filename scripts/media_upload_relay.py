"""Loopback-only CONNECT relay for explicitly approved SSH-forwarded media hosts.

TLS stays between Chromium and the platform. No cookies, signed URLs, bodies,
or keys are inspected. This is opt-in transport recovery, not a login bypass.
"""
import argparse
import asyncio
import json
import re


def parse_target(authority, targets):
    match = re.fullmatch(r'([a-zA-Z0-9.-]+):443', authority)
    if not match:
        return None
    host = match[1].lower()
    return host if host in targets else None


def pac(targets, port):
    hosts = json.dumps(sorted(targets))
    return ('function FindProxyForURL(url, host) {\n'
            f'  var hosts = {hosts};\n'
            f'  if (hosts.indexOf(host.toLowerCase()) >= 0) return "PROXY 127.0.0.1:{port}";\n'
            '  return "DIRECT";\n}\n').encode()


async def handle(reader, writer, targets, port):
    upstream = None
    tasks = []
    try:
        head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
        if len(head) > 8192:
            raise ValueError('oversized request')
        method, authority, version = head.split(b'\r\n', 1)[0].decode('ascii').split(' ')
        if method == 'GET' and authority == '/douyin-upload.pac':
            body = pac(targets, port)
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/x-ns-proxy-autoconfig\r\n'
                         b'Cache-Control: no-store\r\nConnection: close\r\nContent-Length: ' +
                         str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
            return
        host = parse_target(authority, targets) if method == 'CONNECT' and version == 'HTTP/1.1' else None
        if host is None:
            writer.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        upstream_reader, upstream = await asyncio.wait_for(
            asyncio.open_connection('127.0.0.1', targets[host]), 10)
        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await writer.drain()
        print(json.dumps({'event': 'connect', 'host': host}), flush=True)

        async def copy(source, destination):
            count = 0
            while data := await asyncio.wait_for(source.read(65536), 120):
                destination.write(data)
                await asyncio.wait_for(destination.drain(), 120)
                count += len(data)
            return count

        tasks = [asyncio.create_task(copy(reader, upstream)),
                 asyncio.create_task(copy(upstream_reader, writer))]
        done, _ = await asyncio.wait(tasks, timeout=1800, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        print(json.dumps({'event': 'closed', 'host': host}), flush=True)
    except (ValueError, UnicodeError, ConnectionError, OSError, asyncio.TimeoutError,
            asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        print(json.dumps({'event': 'transport_error', 'type': type(exc).__name__}), flush=True)
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for stream in (upstream, writer):
            if stream:
                stream.close()
                try:
                    await stream.wait_closed()
                except (OSError, ConnectionError):
                    pass


async def serve(targets, port):
    active = set()

    async def bounded(reader, writer):
        if len(active) >= 8:
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        active.add(task)
        try:
            await handle(reader, writer, targets, port)
        finally:
            active.discard(task)

    server = await asyncio.start_server(bounded, '127.0.0.1', port, limit=8192)
    print(json.dumps({'event': 'listening', 'address': '127.0.0.1', 'port': port,
                      'hosts': sorted(targets)}), flush=True)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--upstream', action='append', required=True, metavar='HOST=LOCAL_SSH_PORT')
    args = parser.parse_args()
    targets = {}
    for entry in args.upstream:
        host, raw_port = entry.split('=', 1)
        assert re.fullmatch(r'[a-z0-9.-]+', host) and '.' in host
        targets[host] = int(raw_port)
    assert 1024 < args.port < 65536 and all(1024 < p < 65536 for p in targets.values())
    asyncio.run(serve(targets, args.port))


if __name__ == '__main__':
    main()
