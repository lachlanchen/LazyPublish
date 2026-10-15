# Douyin upload recovery and final-submit safety

Separate media transfer, form readiness, submission, and moderation. A logged-in
editor or successful upload is not a published post. A queue `done` row confirms
native submission and management readback, not approval by platform moderators.

The per-platform result also includes `publication_receipt` for Douyin:
`publication_state` is `review_pending`, `published`, `restricted`, `rejected`,
`private`, or `unknown`. Read this field, not just worker `status=done`.
`retry_safe=false` remains set after any attempted final click, including a lost
response. A restricted post must not be reuploaded or edited speculatively to
evade moderation. Inspect the native reason and use the normal review/appeal path.

Receipt matching requires the full approved title + caption and a unique native
timestamp within this submission window. Old same-title posts and ambiguous
duplicates cannot confirm a new post. Native moderation may change later: the
record includes `observed_at` and is not a continuing guarantee of availability.
Before reporting a post live, refresh the native management row and verify its
current status. A later restriction supersedes an earlier pending receipt.

## Recovery rules

- An explicit upload failure gets at most one media-only retry in the same
  editor. Never recursively restart the whole publication workflow.
- Login, verification, account restriction, and rate-limit prompts stop recovery.
- A pending upload with no advancing bytes/percentage for 180 seconds stops with
  evidence, rather than silently reuploading. The normal total bound is one hour.
- Keep sanitized transport diagnostics: host/status/timing only. A recovered
  direct upload does not establish the cause of an earlier intermittent failure.
  Use the opt-in transport relay only after actual route evidence; it is not a
  default proxy or verification workaround.
- A final click sets a no-replay barrier **before** CDP dispatch. A lost response
  never falls through to another click. Post-submit errors require reconciliation.
- Submit acceptance without a management match is a verification failure, not
  success. Preserve the package and check history before any retry.
- Test mode prepares the form and returns False (not published); it does not block
  a queue worker waiting for terminal input or report a canceled attempt as done.

## Per-job reviewed options

The normal `/publish` endpoint accepts:

- `douyin_content_label=ai_generated`: select and verify the native
  `内容由AI生成` declaration. The public caption remains viewer-facing.
- `douyin_resume_sha256=<64 lowercase hex characters>`: explicit operator
  attestation that the current ready draft is the already-inspected upload of
  this exact MP4. The publisher validates the package file hash before reuse.
  Hash equality does not by itself prove which media is in the browser; the
  operator must observe the upload identity/readiness before requesting resume.

The options are validated before staging and saved on that queue job; they do not
mutate the reviewed ZIP or global browser defaults. Without a hash-bound resume,
an existing ready draft is replaced rather than assumed to be the requested
edition. The old global `AUTOPUB_DOUYIN_REUSE_DRAFT=1` flag is rejected without a
per-job hash. Failed/pending drafts are never treated as complete.

Before final submission, title and description are read back. Only metadata tags
are used; no generic trending tags or fabricated filming location is added.

Retry only the missing platform with the unchanged reviewed ZIP bytes and query
options. Do not include previously successful Instagram, YouTube, or Shipinhao.
Preserve the existing profile, pending drafts, receipts and queue journal. Deploy
only when the shared queue is idle and no manual owner operation is running.

## Tests

Run `python -m pytest tests/test_douyin*.py tests/test_local_package.py -q` and
`python -m unittest test_publish_ui_regressions -q` with the publishing environment.
Tests cover upload-only recovery limits, stalls, verification gates, hash-bound
resume, lost click responses, post-submit failures, native readback requirements,
test-mode behavior, and HTTP option validation. Native confirmation remains the
required acceptance check for a real authorized post.
