"""Small, testable bounds for upload recovery and reviewed resume options."""
import re


def publish_options(content_label="", resume_sha256=""):
    if content_label not in {"", "ai_generated"}:
        raise ValueError("Unsupported Douyin content label")
    if resume_sha256 and not re.fullmatch(r"[a-f0-9]{64}", resume_sha256):
        raise ValueError("Douyin resume requires the reviewed media SHA-256")
    return {"content_label": content_label, "resume_sha256": resume_sha256}


def upload_gate(text):
    """Verification/account/rate limits require an operator, never a retry loop."""
    return next((term for term in (
        "请先登录", "请登录后", "安全验证", "请完成验证", "请完成短信验证",
        "操作频繁", "上传视频过快", "请稍后再试", "账号异常", "帐号异常", "权限不足",
    ) if term in (text or "")), None)


class UploadWatch:
    def __init__(self, now, idle_seconds=180, total_seconds=3600):
        self.started = self.last_advance = now
        self.idle_seconds = idle_seconds
        self.total_seconds = total_seconds
        self.maximum_bytes = 0
        self.maximum_percent = 0

    def observe(self, progress, now):
        amount = progress.get("uploaded_bytes", 0)
        percent = progress.get("percent", 0)
        if amount > self.maximum_bytes or percent > self.maximum_percent:
            self.last_advance = now
        self.maximum_bytes = max(self.maximum_bytes, amount)
        self.maximum_percent = max(self.maximum_percent, percent)
        if now - self.started >= self.total_seconds:
            return "upload deadline exceeded"
        if now - self.last_advance >= self.idle_seconds:
            return "upload stopped advancing"
        return None
