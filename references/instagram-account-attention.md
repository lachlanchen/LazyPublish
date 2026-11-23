# Instagram account-attention stop

The browser publisher stops without retrying when it sees a native automated
activity warning or navigates to an Instagram account challenge, checkpoint,
suspension, or disabled-account page. It checks before login and before upload
or Share, then while waiting for confirmation. The check covers recognized
English warning copy and the account routes; it cannot see notifications shown
only on a phone.

If an owner reports a warning, leave Instagram out of the publish job. Keep the
reviewed video and caption. Review the notice in Instagram; if a Share action
may have been sent, verify the profile before attempting the post again. Do not
dismiss the warning, change browser identity, or fall back to another account.

To replace browser publishing, use an account-authorized connector for the
exact destination or [Meta's professional-account Content Publishing API](https://developers.facebook.com/documentation/instagram-platform/content-publishing).
Verify the account, permissions, and final media permalink. Keep other
destinations independent of Instagram account attention.

Offline regression: `python -m unittest discover -s tests -p test_instagram_account_attention.py -v`.
