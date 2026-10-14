# Recover a stalled Douyin media upload

Distinguish authentication, upload transport, and publication. A successful login
or upload-preparation response does not prove the video bytes reached Douyin.

On an observed failed upload, inspect sanitized CDP network events with
`scripts/diagnose_douyin_upload.py`. Retain only host, method, response status,
elapsed time and error type. Signed URLs, cookies and request bodies stay private.
Check the native upload progress and TCP retransmissions. Do not repeatedly
publish or replace the video to test a network hypothesis.

## Optional, explicitly scoped transport recovery

When the direct media route demonstrably stalls and an already-authorized SSH
server has a working route, `scripts/media_upload_relay.py` provides a temporary
loopback-only CONNECT relay. Chromium retains end-to-end TLS with the platform;
the relay neither sees credentials nor changes requests. It is not a proxy for
sign-in, verification, moderation, or bypassing platform restrictions.

1. Inspect the active publisher queue and affected browser/profile. Drain the
   queue before restarting that browser. Preserve the original launch command,
   profile and display privately. Do not restart unrelated channels.
2. Select free loopback ports. Forward one port through pinned, existing SSH
   access to each **actually observed exact upload hostname**, port 443. Do not
   create a wildcard proxy, public listener, DNS override, firewall rule or new
   browser profile.
3. Run the helper with explicit `--upstream HOST=LOCAL_SSH_PORT` mappings. Its PAC
   serves `/douyin-upload.pac`; only listed hosts use the proxy, all others are
   direct. Unlisted CONNECT targets, other methods and non-443 ports are denied.
4. If the browser is on another host, use a pinned SSH reverse forward bound to
   that host's loopback. Keep local/remote relay port numbers equal because the
   PAC advertises its local listening port.
5. Relaunch only the affected, idle browser with the original flags plus
   `--proxy-pac-url=http://127.0.0.1:PORT/douyin-upload.pac`. Never copy profile
   credentials. [Chromium network settings](https://www.chromium.org/developers/design-documents/network-settings/)
   documents the PAC flag.
6. Verify TLS to an allowed target, rejection of an unlisted target, and one
   full upload using an already authorized asset. Do not click Publish during
   diagnosis. Native preview/readiness and upload completion are required;
   a fast handshake alone is insufficient.
7. For actual publication, use the normal queue and exact reviewed package.
   An upload-only probe is not publication evidence. A different edition must
   replace the draft media: do not enable `AUTOPUB_DOUYIN_REUSE_DRAFT` for it.
8. After the queue is finished, restore the browser's original flags before
   stopping the relay and its exact owned SSH processes. Verify listener closure.
   An intentionally persistent route needs its own supervised, least-privilege
   operational review; this helper does not silently install one.

Example with placeholder values, after the actual hosts and ports are reviewed:

```sh
python scripts/media_upload_relay.py --port 28440 \
  --upstream observed-media.example=28441
python -m unittest tests.test_media_upload_relay -v
```

The helper bounds concurrency, headers, connection setup, inactivity and tunnel
lifetime. It does not establish that every future CDN hostname or network route
will work. Reconcile failures before retrying and retain the native outcome.

## Distinct editions and YouTube drafts

A same-title private draft can contain another edition of the media. Before
republishing a revised video, preserve and close the old saved draft and verify
the old wizard is gone. Do not treat title equality as media identity. If a
saved wizard becomes unresponsive, a narrowly targeted tab recovery may be
needed; do not discard an unsaved upload or bypass pending platform checks.
