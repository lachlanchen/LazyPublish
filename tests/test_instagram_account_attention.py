import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch

from instagram_account_attention import (
    InstagramAccountAttentionError,
    require_instagram_account_ready,
)

utils_stub = ModuleType("utils")
for name in ("SendMail", "dismiss_alert", "bring_to_front", "close_extra_tabs"):
    setattr(utils_stub, name, Mock())
with patch.dict(sys.modules, {"utils": utils_stub}):
    import login_instagram as login_module
    from login_instagram import InstagramLogin
    from pub_instagram import InstagramPublisher


class InstagramAccountAttentionTests(TestCase):
    def driver_with_notice(self, *, visible=True):
        driver = Mock(current_url="https://www.instagram.com/")
        notice = Mock(text="We suspect automated behavior\non your account")
        notice.is_displayed.return_value = visible
        driver.find_elements.return_value = [notice]
        return driver

    def test_visible_notice_stops_login_before_navigation(self):
        login = InstagramLogin.__new__(InstagramLogin)
        login.driver = self.driver_with_notice()
        with self.assertRaises(InstagramAccountAttentionError):
            login.check_and_act()
        login.driver.get.assert_not_called()

    def test_notice_loaded_on_home_is_not_dismissed(self):
        login = InstagramLogin.__new__(InstagramLogin)
        login.driver = self.driver_with_notice()
        login.driver.current_url = "about:blank"

        def show_home(url):
            login.driver.current_url = url

        login.driver.get.side_effect = show_home
        with patch.object(login_module.time, "sleep"), patch.object(login_module, "dismiss_alert") as dismiss:
            with self.assertRaises(InstagramAccountAttentionError):
                login.check_and_act()
        dismiss.assert_not_called()

    def test_account_challenge_stops_publish_without_retry(self):
        publisher = InstagramPublisher.__new__(InstagramPublisher)
        publisher.driver = Mock(current_url="https://www.instagram.com/challenge/example/")
        publisher.retry_count = 0
        with self.assertRaises(InstagramAccountAttentionError):
            publisher.publish()
        publisher.driver.get.assert_not_called()
        self.assertEqual(publisher.retry_count, 0)

    def test_hidden_notice_does_not_block(self):
        require_instagram_account_ready(self.driver_with_notice(visible=False))

    def test_unrelated_heading_and_non_instagram_challenge_do_not_block(self):
        driver = self.driver_with_notice()
        driver.find_elements.return_value[0].text = "Create new post"
        require_instagram_account_ready(driver)
        driver.reset_mock()
        driver.current_url = "https://example.org/challenge/"
        require_instagram_account_ready(driver)
        driver.find_elements.assert_not_called()
