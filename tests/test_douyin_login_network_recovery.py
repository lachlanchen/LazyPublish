"""Network failures must not be misreported as missing login QR codes."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def recover(texts):
    source = Path(__file__).parents[1] / "login_douyin.py"
    tree = ast.parse(source.read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "recover_network_error")
    safe_get, sleep = Mock(), Mock()
    scope = {"safe_get": safe_get, "time": SimpleNamespace(sleep=sleep)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
    driver = SimpleNamespace(execute_script=Mock(side_effect=texts))
    return lambda: scope["recover_network_error"](SimpleNamespace(driver=driver), "https://creator.douyin.com/creator-micro/content/upload"), safe_get


@pytest.mark.parametrize("text", ["作品发布 上传视频", "扫码登录", ""])
def test_normal_or_login_page_does_not_reload(text):
    run, reload = recover([text])
    run()
    reload.assert_not_called()


def test_transient_network_page_reloads_once_then_preserves_login():
    run, reload = recover(["加载中...\n网络请求错误，请刷新页面重试", "作品发布 上传视频"])
    run()
    assert reload.call_count == 1


def test_persistent_network_error_is_bounded_and_explicit():
    run, reload = recover(["网络请求错误"] * 3)
    with pytest.raises(RuntimeError, match="login state is unknown and no upload"):
        run()
    assert reload.call_count == 2


def test_network_recovery_runs_before_login_detection():
    tree = ast.parse((Path(__file__).parents[1] / "login_douyin.py").read_text())
    check = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "check_and_act")
    calls = [n for n in ast.walk(check) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)]
    recovery = next(n.lineno for n in calls if n.func.attr == "recover_network_error")
    detection = min(n.lineno for n in calls if n.func.attr == "is_already_logged_in")
    assert recovery < detection


def test_skip_login_option_does_not_trigger_qr_or_email():
    source = Path(__file__).parents[1] / "login_douyin.py"
    tree = ast.parse(source.read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "check_and_act")
    scope = {"safe_get": Mock(), "time": SimpleNamespace(sleep=Mock()),
             "dismiss_alert": Mock(), "bring_to_front": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
    fake = Mock()
    fake.is_already_logged_in.return_value = False
    with pytest.raises(RuntimeError, match="skipped by job option"):
        scope["check_and_act"](fake, allow_interactive_login=False)
    fake.click_login_button.assert_not_called()
    fake.take_screenshot_and_send_email.assert_not_called()


def test_skip_login_option_does_not_skip_an_authenticated_account():
    source = Path(__file__).parents[1] / "login_douyin.py"
    method = next(n for n in ast.walk(ast.parse(source.read_text()))
                  if isinstance(n, ast.FunctionDef) and n.name == "check_and_act")
    scope = {"safe_get": Mock(), "time": SimpleNamespace(sleep=Mock()),
             "dismiss_alert": Mock(), "bring_to_front": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
    fake = Mock()
    fake.is_already_logged_in.return_value = True
    assert scope["check_and_act"](fake, allow_interactive_login=False) is True
