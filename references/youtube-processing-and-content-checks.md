# Distinguish media processing from completed content checks

YouTube Studio can show both `Copyright / No issues found` and `Community Guidelines / No issues found` in the current upload dialog while its footer shows `Processing up to HD` or `Video processing is taking longer than expected. Please wait.` Requiring the footer to say `Checks complete` made the publisher wait until its 15-minute limit despite the explicit content-check results.

The shared check interpreter now accepts those two native subcheck results together when the footer is showing media processing. A generic success label, one completed subcheck, a clickable Next button, an active Checking footer, or a prechecks warning does not qualify. Existing copyright-claim review rules remain in force.

The publisher still uses normal enabled navigation and publication controls and requires a native publication receipt. This does not bypass a disabled control, choose Publish anyway, or claim that HD processing has finished. If YouTube itself blocks publication, preserve the existing upload. Recovery must resume the matching open draft instead of attaching the media again.

The upload-phase wait also recognizes the native processing-delay message as evidence that uploading has finished. Without that marker, resuming this saved draft could wait another 30 minutes for an `Upload complete` footer that Studio had already replaced. This advances only the upload-phase wait; the separate content-check and publication-receipt requirements still apply.

Validation:

```sh
PYTHONPATH=. python -m unittest discover -s tests -p test_youtube_check_flow.py -v
```

Deploy only at an idle queue boundary. Reload the API worker with its original arguments, protected environment and queue journal; preserve Chromium profiles and the unfinished YouTube dialog. Do not restart the entire application or the browser to activate this Python-only fix.
