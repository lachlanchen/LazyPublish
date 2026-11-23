from urllib.parse import urlsplit

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By


class InstagramAccountAttentionError(RuntimeError):
    """A native warning or account challenge requires a person, not a retry."""


def require_instagram_account_ready(driver):
    url = urlsplit(driver.current_url or "")
    host = url.hostname or ""
    if host != "instagram.com" and not host.endswith(".instagram.com"):
        return

    message = (
        "Instagram requires account attention. Browser publishing stopped; "
        "review the native notice before retrying."
    )
    paths = ("/challenge", "/checkpoint", "/accounts/suspended", "/accounts/disabled")
    path = url.path.rstrip("/")
    if any(path == prefix or path.startswith(prefix + "/") for prefix in paths):
        raise InstagramAccountAttentionError(message)

    notices = (
        "automated behavior on your account",
        "automated behaviour on your account",
        "we detected automated activity on your account",
    )
    selector = "[role='alertdialog'], [role='dialog'], [role='alert'], h1, h2, [role='heading']"
    for element in driver.find_elements(By.CSS_SELECTOR, selector):
        try:
            if element.is_displayed():
                text = " ".join(element.text.casefold().split())
                if any(notice in text for notice in notices):
                    raise InstagramAccountAttentionError(message)
        except StaleElementReferenceException:
            continue
