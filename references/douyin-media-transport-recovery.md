# Recover a stalled Douyin media upload

Distinguish authentication, upload transport, and publication. A successful login
or upload-preparation response does not prove the video bytes reached Douyin.

On an observed failed upload, inspect sanitized CDP network events with
`scripts/diagnose_douyin_upload.py`. Retain only host, method, response status,
elapsed time and error type. Signed URLs, cookies and request bodies stay private.
Check the native upload progress and TCP retransmissions. Do not repeatedly
publish or replace the video to test a network hypothesis.

The page-level diagnostic can miss transfers made by dedicated Web Workers.
Successful preparation requests are not evidence that the media chunks arrived.
When the visible byte counter stalls, inspect the browser's `Target.getTargets`
worker entries, attach read-only sessions with `flatten=true`, and enable
`Network` on those sessions without pausing execution. Track requests by both
session ID and request ID; detach the diagnostic sessions afterward. Keep the
same host/status/timing-only logging boundary.

In one observed failure, worker uploads selected `tos-nc2-slb1.douyin.com` and
`tos-nc2-slb2.douyin.com`, while page requests used different media hosts. Chunk
POSTs on the direct route were canceled at about 60 seconds. Adding those exact
observed hosts to the temporary relay allowed the unchanged package to finish.
Derive the allowlist from the current upload, not a previous video's host list.
A quick TLS handshake or a fast initial progress estimate does not qualify the
route: require native upload completion and the separate publication receipt.

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

The connection limit is 32. Chromium may retain several connections per media
host while contacting additional upload hosts; the previous eight-connection
limit could silently drop valid parallel requests. Excess connections now get
HTTP 503 and a `capacity_rejected` log entry. A loopback regression opens 32
opaque TLS-style streams, verifies byte transport, and checks the overflow bound.
This fixes relay capacity; it does not prove the cause of a native upload failure.

Idle timeout is now shared across both directions. A media server may wait for
the complete POST body before returning anything; timing out its quiet response
direction after 120 seconds can cancel a healthy, still-progressing upload.
Either-direction byte activity now keeps the tunnel alive. Truly idle tunnels,
blocked drains, the 30-minute lifetime and the 32-connection cap remain bounded.
A loopback regression reproduced the old false disconnect during a slow one-way
upload; that scenario and a truly idle tunnel now pass (nine relay tests total).
This fixes a transport failure mode, not every possible CDN or native failure.

## Distinct editions and YouTube drafts

A same-title private draft can contain another edition of the media. Before
republishing a revised video, preserve and close the old saved draft and verify
the old wizard is gone. Do not treat title equality as media identity. If a
saved wizard becomes unresponsive, a narrowly targeted tab recovery may be
needed; do not discard an unsaved upload or bypass pending platform checks.
