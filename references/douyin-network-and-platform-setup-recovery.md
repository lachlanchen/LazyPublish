# Recover a failed Douyin page before requesting login

Douyin can display `加载中... 网络请求错误，请刷新页面重试` in a browser that still has a valid login. The old login flow treated this as a changed login form and sent a screenshot email without a QR. A same-tab reload recovered the authenticated upload page in the observed failure.

The login flow now checks that explicit network error before login detection and reloads the same URL at most twice. A persistent failure reports an unknown login state and stops before upload. Genuine login pages keep the existing QR flow and long login wait.

For a job that should proceed only with the existing login, pass `douyin_skip_login=true` to `/publish`. The job retains this option in `douyin_options`; it stops before opening QR/email login if authentication is needed. Omit the option for normal interactive login behavior. This does not change saved account settings or reduce the usual login wait.

Publisher constructors may navigate or request login. They are now deferred into the existing sequential batch's per-platform failure boundary. A setup failure is recorded for that platform, while other selected platforms continue. No second publisher, parallel browser worker or new queue is added. Native post-submission receipts still govern retry safety.

If a job failed during setup before any platform result or submission existed, reuse its verified ZIP for the unsubmitted targets. If native results contain a submitted or ambiguous target, reconcile it and retry only proven missing targets. Never infer submission from an enabled button or a model response.

Tests exercise network recovery, persistent failure, genuine login pages, opt-out before QR/email, authenticated opt-out, exact per-job API options and constructor-failure isolation:

```bash
python -m pytest tests/test_douyin_login_network_recovery.py tests/test_publish_batch.py tests/test_hosted_account_detection.py tests/test_douyin_recovery.py tests/test_douyin_draft_resume.py tests/test_local_package.py -q
```

Activate production code only after the native queue is idle; preserve the journal, browser profiles and exact API startup environment. An active native upload continues on its existing process until completion.
