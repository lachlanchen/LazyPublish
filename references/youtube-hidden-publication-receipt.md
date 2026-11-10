# Reconcile a hidden YouTube success receipt

Studio can hide its completed share dialog while retaining a saving scrim on
the upload wizard. The visible-only receipt check then reports an uncertain
outcome even though the exact video is public. Do not upload it again.

The publisher retains normal visible-receipt verification. Its bounded fallback
requires all of the following:

- This publisher has already attached/resumed an upload.
- The current wizard exposes an exact 11-character video ID.
- A native completed receipt contains that same ID and the reviewed title.
- YouTube's public oEmbed endpoint returns HTTP 200 for that ID and the exact
  reviewed title.

A hidden stale receipt for another ID, a draft title or a private/unavailable
video does not pass. The probe sends no account cookies or credentials, has a
ten-second timeout and caches the result briefly. Confirmed completion can
return to the existing Studio content page without uploading or publishing
again. The fallback does not enable a disabled publish control or bypass checks.

Regression command:

```sh
python -m unittest discover -s tests -p test_youtube_check_flow.py -v
```

The suite covers public matching receipt acceptance, stale ID rejection and
private-video rejection alongside the existing no-duplicate checks. Operator
reconciliation of a historical failed queue row must retain its prior error
and independent receipt evidence; update only the proven platform result at
an idle worker boundary.
