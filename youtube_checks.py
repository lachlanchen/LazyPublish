"""Interpret the upload's check status, not navigation controls or old posts."""

import re


def checks_outcome(progress, details="", warning=False):
    if warning:
        return "pending"
    progress = (progress or "").lower()
    details = (details or "").lower().replace("\u2019", "'")
    if "checks complete" not in progress:
        # Studio replaces the footer's checks result with media processing
        # progress. Read both explicit subcheck results in the current upload
        # dialog; a ready Next button or one generic success label is not proof.
        media_processing = (
            "processing up to hd" in progress
            or "video processing is taking longer than expected" in progress
        )
        clear_subchecks = all(
            re.search(r"(?:^|\n)\s*" + re.escape(label)
                      + r"\s*\n\s*no issues found\s*(?:\n|$)", details)
            for label in ("copyright", "community guidelines")
        )
        if media_processing and clear_subchecks:
            return "complete"
        return "pending"
    if "no issues found" in progress:
        return "complete"
    if "claimed content found" in progress:
        if "this claim doesn't affect your video's visibility or features" in details:
            return "complete"
        return "review"
    return "review"
