"""Native management content must be read through visible application frames."""
import ast
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright


class ManagementFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'publish_verification.py'
        cls.script = next(ast.literal_eval(n.value) for n in ast.parse(source.read_text()).body
                          if isinstance(n, ast.Assign)
                          and isinstance(n.targets[0], ast.Name)
                          and n.targets[0].id == 'COLLECT_TEXT_SCRIPT')
        publisher = source.with_name('pub_shipinhao.py')
        cls.click_script = next(ast.literal_eval(n.value) for n in ast.parse(publisher.read_text()).body
                                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                                and n.targets[0].id == 'CONTENT_FRAME_CLICK_SCRIPT')
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def text(self):
        return self.page.evaluate('(s) => Function(s)()', self.script)

    def test_visible_iframe_contains_actual_management_receipt(self):
        self.page.set_content('<p>Channel assistant</p><iframe srcdoc="<p>SPIE toast published</p>"></iframe>')
        self.page.frame_locator('iframe').get_by_text('SPIE toast published').wait_for()
        self.assertIn('SPIE toast published', self.text())

    def test_hidden_old_iframe_does_not_prove_current_publication(self):
        self.page.set_content('<iframe style="display:none" srcdoc="<p>Old SPIE toast</p>"></iframe>')
        self.assertNotIn('SPIE', self.text())

    def test_shadow_content_is_retained_but_css_is_not_a_receipt(self):
        self.page.set_content('<div id="host"></div>')
        self.page.evaluate('''document.querySelector('#host').attachShadow({mode:'open'}).innerHTML =
          '<style>/* Fake receipt */</style><p>Actual receipt</p>';''')
        self.assertIn('Actual receipt', self.text())
        self.assertNotIn('Fake receipt', self.text())

    def test_content_button_dispatches_exactly_one_click(self):
        self.page.set_content('<button onclick="window.clicks=(window.clicks||0)+1">发表</button>')
        clicked = self.page.evaluate('(s) => Function(s)("button", "发表", true, true)', self.click_script)
        self.assertTrue(clicked)
        self.assertEqual(self.page.evaluate('window.clicks'), 1)

    def test_class_disabled_content_button_is_not_clicked(self):
        self.page.set_content('<button class="weui-desktop-btn_disabled" onclick="window.clicked=true">发表</button>')
        self.assertFalse(self.page.evaluate('(s) => Function(s)("button", "发表", true, true)', self.click_script))
        self.assertFalse(self.page.evaluate('!!window.clicked'))


if __name__ == '__main__':
    unittest.main()
