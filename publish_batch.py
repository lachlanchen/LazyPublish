"""Finish independent targets, preserving partial success for scoped retries."""


def publish_batch(publishers, publish, *, before_each=None, on_result=None):
    results = {}
    for publisher, name in publishers:
        if on_result:
            on_result(name, {"status": "running"})
        try:
            if before_each:
                before_each(name)
            if publish(publisher, name) is False:
                raise RuntimeError("Publisher returned unsuccessful status")
        except Exception as exc:
            results[name] = {"status": "failed", "error": str(exc)}
        else:
            results[name] = {"status": "done", "error": None}
        receipt = getattr(publisher, "publication_receipt", None)
        if isinstance(receipt, dict):
            # done means the worker finished, not that moderation approved it.
            results[name]["publication_receipt"] = dict(receipt)
        if on_result:
            on_result(name, results[name])
    failures = [f"{name}: {r['error']}" for name, r in results.items() if r["status"] == "failed"]
    if failures:
        reconcile = [name for name, r in results.items()
                     if r.get("publication_receipt", {}).get("retry_safe") is False]
        if reconcile:
            raise RuntimeError("Some platforms failed: " + "; ".join(failures)
                               + ". Reconcile submitted targets; do not retry: " + ", ".join(reconcile))
        raise RuntimeError("Some platforms failed; retry only failed targets: " + "; ".join(failures))
    return results
