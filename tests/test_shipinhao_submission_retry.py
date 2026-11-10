"""A lost acknowledgment must never turn into a second whole publication."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def publisher_fixture():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'pub_shipinhao.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ShiPinHaoPublisher')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'publish')
    helpers = ['dismiss_alert', 'bring_to_front', 'close_extra_tabs', 'wait_for_publish_page_ready',
               'find_any_in_content_frame', 'send_file_to_content_frame', 'wait_for_post_upload_editor_ready',
               'ensure_content_frame_editable_value', 'select_content_frame_collection',
               'ensure_content_frame_input_value', 'wait_for_cover_ready',
               'ensure_content_frame_checkbox_value', 'click_content_frame_css',
               'click_content_frame_draft_if_available', 'wait_for_publish_button_ready',
               'verify_publish_in_management', 'save_debug_snapshot']
    scope = {name: Mock(return_value=True) for name in helpers}
    scope.update(time=SimpleNamespace(sleep=Mock(), time=Mock(return_value=0)),
                 os=SimpleNamespace(environ={}), traceback=SimpleNamespace(print_exc=Mock()),
                 print=Mock(), remove_non_bmp=lambda text: text,
                 resolve_shipinhao_collection=lambda *a, **k: '简单生活',
                 is_upload_complete_indicator_present=Mock(return_value=True))
    for name in ['SHIPINHAO_CREATE_URL', 'SHIPINHAO_MANAGEMENT_URL',
                 'SHIPINHAO_WINDOW_PATTERNS', 'SHIPINHAO_UPLOAD_INPUT_SELECTORS',
                 'SHIPINHAO_SHORT_TITLE_SELECTOR']:
        scope[name] = name
    scope['ensure_content_frame_editable_value'].return_value = 'description'
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<publisher-method>', 'exec'), scope)
    publisher = type('Publisher', (), {'publish': scope['publish']})()
    publisher.driver = Mock()
    publisher.video_path = 'reviewed.mp4'
    publisher.thumbnail_path = 'cover.jpg'
    publisher.metadata = {'title': 'SPIE', 'long_description': 'A toast', 'tags': []}
    publisher.test = False
    publisher.retry_count = 0
    publisher.build_short_title = Mock(return_value='SPIE')
    return publisher, scope


class SubmissionRetryTests(unittest.TestCase):
    def test_failed_management_verification_never_reuploads(self):
        publisher, scope = publisher_fixture()
        scope['verify_publish_in_management'].side_effect = RuntimeError('listing unavailable')
        with self.assertRaisesRegex(RuntimeError, 'outcome is uncertain'):
            publisher.publish()
        self.assertEqual(scope['send_file_to_content_frame'].call_count, 1)
        clicks = [c for c in scope['click_content_frame_css'].call_args_list
                  if c.kwargs.get('text') == '发表']
        self.assertEqual(len(clicks), 1)

    def test_publish_click_timeout_is_also_uncertain(self):
        publisher, scope = publisher_fixture()
        def click(*args, **kwargs):
            if kwargs.get('text') == '发表':
                raise TimeoutError('lost click acknowledgment')
        scope['click_content_frame_css'].side_effect = click
        with self.assertRaisesRegex(RuntimeError, 'outcome is uncertain'):
            publisher.publish()
        self.assertEqual(scope['send_file_to_content_frame'].call_count, 1)

    def test_safe_pre_submission_failure_retains_bounded_retry(self):
        publisher, scope = publisher_fixture()
        scope['wait_for_publish_page_ready'].side_effect = [RuntimeError('page loading'), True]
        self.assertTrue(publisher.publish())
        self.assertEqual(publisher.driver.get.call_count, 2)
        self.assertEqual(scope['send_file_to_content_frame'].call_count, 1)
        self.assertEqual(scope['verify_publish_in_management'].call_count, 1)


if __name__ == '__main__':
    unittest.main()
