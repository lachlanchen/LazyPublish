import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from douyin_policy import UploadWatch, publish_options, upload_gate, management_receipt

utils = types.ModuleType("utils")
for name in ("dismiss_alert", "bring_to_front", "close_extra_tabs", "safe_get"):
    setattr(utils, name, Mock())
login = types.ModuleType("login_douyin")
login.DouyinLogin = Mock()
spec = importlib.util.spec_from_file_location("douyin_recovery_test", Path(__file__).resolve().parents[1] / "pub_douyin.py")
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"utils": utils, "login_douyin": login}):
    spec.loader.exec_module(module)


class PolicyTests(unittest.TestCase):
    def test_receipt_distinguishes_submission_and_publication(self):
        row = {"caption": "A title The description", "time": "2026年10月16日 00:08", "duration": "00:50"}
        for status, state in (("审核中", "review_pending"), ("已发布", "published"),
                              ("不适宜公开", "restricted"), ("未通过", "rejected"),
                              ("仅自己可见", "private"), ("new unknown status", "unknown")):
            receipt = management_receipt([{**row, "status": status}], "A title", "The description",
                                         datetime(2026, 10, 16, 0, 8, 45))
            self.assertEqual(receipt["publication_state"], state)
            self.assertFalse(receipt["retry_safe"])

    def test_old_wrong_caption_and_ambiguous_rows_cannot_confirm_new_post(self):
        row = {"caption": "A title The description", "time": "2026年10月16日 00:08", "status": "已发布"}
        for rows in ([{**row, "time": "2026年10月15日 00:08"}],
                     [{**row, "caption": "A title Another description"}],
                     [{**row, "time": "unknown"}], [row, row], []):
            with self.assertRaises(ValueError):
                management_receipt(rows, "A title", "The description", datetime(2026, 10, 16, 0, 8))

    def test_options_are_bounded_and_exact(self):
        self.assertEqual(publish_options(), {"content_label": "", "resume_sha256": ""})
        self.assertEqual(publish_options("ai_generated", "a" * 64)["resume_sha256"], "a" * 64)
        for label, digest in (("made_up", ""), ("", "a" * 63), ("", "A" * 64), ("", "a" * 64 + "\n")):
            with self.assertRaises(ValueError):
                publish_options(label, digest)

    def test_only_advancing_bytes_or_percent_reset_idle_timer(self):
        watch = UploadWatch(0, idle_seconds=10)
        self.assertIsNone(watch.observe({"uploaded_bytes": 100, "percent": 1}, 4))
        self.assertIsNone(watch.observe({"uploaded_bytes": 100, "percent": 1}, 12))
        self.assertEqual(watch.observe({"uploaded_bytes": 99, "percent": 1}, 14), "upload stopped advancing")

    def test_total_deadline_even_with_progress(self):
        self.assertEqual(UploadWatch(0, total_seconds=20).observe({"percent": 10}, 20), "upload deadline exceeded")

    def test_verification_and_rate_limits_are_not_transport_retry_signals(self):
        for text in ("请完成短信验证", "上传视频过快", "账号异常", "操作频繁"):
            self.assertIsNotNone(upload_gate(text))
        self.assertIsNone(upload_gate("上传失败，重新上传"))


class RecoveryTests(unittest.TestCase):
    def publisher(self, bodies):
        p = module.DouyinPublisher.__new__(module.DouyinPublisher)
        p.path_mp4 = "/reviewed/video.mp4"
        p._body_text = Mock(side_effect=bodies)
        p._upload_video_file = Mock(return_value=None)
        p._save_upload_debug_snapshot = Mock(return_value=("evidence/failure", {}))
        p._submit_attempted = False
        return p

    def test_one_failed_upload_recovers_in_place(self):
        p = self.publisher(["上传失败，重新上传", "预览视频\n重新上传"])
        with patch.object(module.time, "sleep"):
            p._wait_for_upload()
        p._upload_video_file.assert_called_once_with(p.path_mp4)

    def test_two_failures_stop_without_whole_job_retry(self):
        p = self.publisher(["上传失败", "上传失败"])
        with patch.object(module.time, "sleep"), self.assertRaises(module.UploadFailedException):
            p._wait_for_upload()
        p._upload_video_file.assert_called_once()

    def test_verification_never_retries(self):
        p = self.publisher(["上传失败\n请完成短信验证"])
        with self.assertRaises(module.UploadFailedException):
            p._wait_for_upload()
        p._upload_video_file.assert_not_called()

    def test_pending_stall_is_not_reuploaded(self):
        p = self.publisher(["正在上传 1%", "正在上传 1%"])
        with patch.object(module.time, "sleep"), patch.object(module.time, "monotonic", side_effect=[0, 0, 181]):
            with self.assertRaisesRegex(module.UploadFailedException, "stopped advancing"):
                p._wait_for_upload()
        p._upload_video_file.assert_not_called()

    def test_ready_upload_is_not_reuploaded(self):
        p = self.publisher(["预览视频\n重新上传"])
        p._wait_for_upload()
        p._upload_video_file.assert_not_called()

    def test_no_upload_recovery_after_submit(self):
        p = self.publisher(["上传失败"])
        p._submit_attempted = True
        with self.assertRaises(module.UploadFailedException):
            p._wait_for_upload()
        p._upload_video_file.assert_not_called()

    def test_hash_bound_resume_rejects_other_media(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.publisher([])
            source = Path(root) / "video.mp4"
            source.write_bytes(b"verified media")
            p.path_mp4 = str(source)
            p.metadata = {"_douyin_options": {"resume_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
            self.assertTrue(p._allow_draft_reuse())
            source.write_bytes(b"another edition")
            with self.assertRaises(ValueError):
                p._allow_draft_reuse()

    def test_global_unbound_resume_is_rejected(self):
        p = self.publisher([])
        p.metadata = {}
        with patch.dict(os.environ, {"AUTOPUB_DOUYIN_REUSE_DRAFT": "1"}), self.assertRaises(ValueError):
            p._allow_draft_reuse()

    def test_lost_final_click_response_never_falls_back(self):
        p = self.publisher([])
        p.driver = Mock()
        p.driver.execute_script.side_effect = TimeoutError("response lost")
        p._click_first = Mock()
        with self.assertRaises(module.PublishVerificationException):
            p._click_publish_button()
        with self.assertRaises(module.PublishVerificationException):
            p._click_publish_button()
        self.assertTrue(p._submit_attempted)
        self.assertFalse(p.publication_receipt["retry_safe"])
        self.assertEqual(p.driver.execute_script.call_count, 1)
        p._click_first.assert_not_called()

    def test_instance_cannot_replay_after_submit(self):
        p = self.publisher([])
        p._submit_attempted = True
        with self.assertRaises(module.PublishVerificationException):
            p.publish()


class FlowTests(unittest.TestCase):
    def ready_publisher(self):
        p = module.DouyinPublisher.__new__(module.DouyinPublisher)
        p.driver = Mock()
        p.driver.execute_script.side_effect = [
            {"title": "Reviewed", "description": "Reviewed description"}, {"found": False}]
        p.path_mp4, p.path_cover = "reviewed.mp4", "cover.jpg"
        p.metadata = {"title": "Reviewed", "long_description": "Reviewed description"}
        p.test, p.retry_count, p._submit_attempted = False, 0, False
        for method in ("_set_input_value", "_set_text", "_set_content_label", "_wait_for_upload",
                       "_find_first", "_upload_video_file", "_replace_existing_draft_video"):
            setattr(p, method, Mock())
        p._allow_draft_reuse = Mock(return_value=True)
        p._verified_editor = Mock(return_value=True)
        p._resume_unpublished_draft_if_present = Mock(return_value=True)
        p._body_text = Mock(return_value="预览视频\n重新上传")
        def click():
            p._submit_attempted = True
        p._click_publish_button = Mock(side_effect=click)
        p._wait_for_publish_submit_result = Mock(return_value=True)
        p._management_receipt = Mock(return_value={"publication_state": "review_pending", "retry_safe": False})
        return p

    def test_test_mode_does_not_block_for_input_or_report_publication(self):
        p = self.ready_publisher()
        p.test = True
        with patch.object(module.time, "sleep"), patch("builtins.input") as prompt:
            self.assertFalse(p.publish())
        prompt.assert_not_called()
        p._click_publish_button.assert_not_called()

    def test_post_click_error_never_restarts_workflow(self):
        p = self.ready_publisher()
        p._wait_for_publish_submit_result.side_effect = TimeoutError("unknown result")
        with patch.object(module.time, "sleep"), self.assertRaises(module.PublishVerificationException):
            p.publish()
        p._click_publish_button.assert_called_once()
        p._wait_for_upload.assert_called_once()
        p._upload_video_file.assert_not_called()

    def test_management_missing_is_not_success_after_accepted_submit(self):
        p = self.ready_publisher()
        with patch.object(module.time, "sleep"), patch.object(module, "verify_publish_in_management", side_effect=RuntimeError("not indexed")):
            with self.assertRaisesRegex(module.PublishVerificationException, "confirmation is pending"):
                p.publish()
        p._click_publish_button.assert_called_once()

    def test_complete_management_confirmation_is_success(self):
        p = self.ready_publisher()
        with patch.object(module.time, "sleep"), patch.object(module, "verify_publish_in_management", return_value=True) as verify:
            self.assertTrue(p.publish())
        verify.assert_called_once()
        p._click_publish_button.assert_called_once()

    def test_native_restriction_is_not_success_or_retried(self):
        p = self.ready_publisher()
        p._management_receipt.return_value = {"publication_state": "restricted", "retry_safe": False}
        with patch.object(module.time, "sleep"), patch.object(module, "verify_publish_in_management", return_value=True):
            with self.assertRaisesRegex(module.PublishVerificationException, "restricted"):
                p.publish()
        p._click_publish_button.assert_called_once()
        self.assertFalse(p.publication_receipt["retry_safe"])

    def test_unbound_ready_upload_is_replaced(self):
        p = self.ready_publisher()
        p.test = True
        p._allow_draft_reuse.return_value = False
        p._resume_unpublished_draft_if_present.return_value = False
        with patch.object(module.time, "sleep"):
            self.assertFalse(p.publish())
        p._replace_existing_draft_video.assert_called_once_with(p.path_mp4)

    def test_caption_mismatch_stops_before_publish(self):
        p = self.ready_publisher()
        p.driver.execute_script.side_effect = [{"title": "Reviewed", "description": "truncated"}]
        with patch.object(module.time, "sleep"), self.assertRaisesRegex(RuntimeError, "readback mismatch"):
            p.publish()
        p._click_publish_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
