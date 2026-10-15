import selenium
from selenium import webdriver
import pathlib
import time
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, TimeoutException, NoAlertPresentException
from selenium.common.exceptions import WebDriverException, ElementClickInterceptedException, StaleElementReferenceException


from utils import dismiss_alert, bring_to_front, close_extra_tabs, safe_get
from login_douyin import DouyinLogin

import traceback
import os
import json
import hashlib
from datetime import datetime
from urllib.parse import urlsplit

from publish_verification import verify_publish_in_management
from douyin_submit import submit_outcome, upload_outcome, upload_progress
from douyin_policy import UploadWatch, upload_gate, publish_options, management_receipt


DOUYIN_MANAGEMENT_URL = "https://creator.douyin.com/creator-micro/content/manage"

class UploadFailedException(Exception):
    """Exception raised when the video upload fails."""
    def __init__(self, message="Video upload failed"):
        self.message = message
        super().__init__(self.message)


class UploadInputMissingException(Exception):
    """Raised when Douyin's upload page does not expose a usable file input."""


class PublishVerificationException(Exception):
    """Raised when the post is submitted but not visible in management."""

class DouyinPublisher:
    def __init__(self, driver, path_mp4, path_cover, metadata, test=False):
        self.driver = driver
        self.path_mp4 = path_mp4
        self.path_cover = path_cover
        self.metadata = metadata
        self.test = test
        self.retry_count = 0  # initialize retry count
        self._submit_attempted = False
        self.publication_receipt = None

        if self._verified_editor():
            print("Reusing the reviewed ready Douyin editor without navigating away.")
        else:
            douyin_login = DouyinLogin(driver)
            douyin_login.check_and_act()

    def _verified_editor(self):
        return (self._allow_draft_reuse()
                and urlsplit(self.driver.current_url).path == "/creator-micro/content/post/video"
                and upload_outcome(self._body_text()) == "ready")

    def _management_receipt(self, title, description, submitted_at):
        cards = self.driver.execute_script("""
          return Array.from(document.querySelectorAll('[class*="video-card-info-"]')).map(info => ({
            caption: info.querySelector('[class*="info-title-text-"]')?.innerText || '',
            time: info.querySelector('[class*="info-time-"]')?.innerText || '',
            status: info.querySelector('[class*="info-status-"]')?.innerText || '',
            duration: info.parentElement.querySelector('[class*="badge-"]')?.innerText || ''
          }));
        """)
        return management_receipt(cards, title, description, submitted_at)

    def _find_first(self, xpaths, timeout=20, visible=True):
        condition = EC.visibility_of_element_located if visible else EC.presence_of_element_located
        last_exc = None
        for xpath in xpaths:
            try:
                return WebDriverWait(self.driver, timeout).until(condition((By.XPATH, xpath)))
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc

    def _find_any(self, xpaths, timeout=5, visible=True):
        for xpath in xpaths:
            try:
                condition = EC.visibility_of_element_located if visible else EC.presence_of_element_located
                WebDriverWait(self.driver, timeout).until(condition((By.XPATH, xpath)))
                return True
            except Exception:
                continue
        return False

    def _safe_click(self, element):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass
        try:
            self.driver.execute_script(
                "const el = arguments[0]; setTimeout(() => el.click(), 0);",
                element,
            )
            time.sleep(0.5)
            return True
        except Exception:
            try:
                element.click()
                return True
            except Exception:
                return False

    def _click_first(self, xpaths, timeout=20):
        element = self._find_first(xpaths, timeout=timeout)
        if not self._safe_click(element):
            raise WebDriverException("Failed to click element.")

    def _click_any(self, xpaths, timeout=5):
        for xpath in xpaths:
            try:
                element = self._find_first([xpath], timeout=timeout)
                if self._safe_click(element):
                    return True
            except Exception:
                continue
        return False

    def _body_text(self):
        try:
            return self.driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        except Exception:
            return ""

    def _debug_dir(self):
        root = os.environ.get("AUTOPUB_DEBUG_DIR") or os.path.join(os.getcwd(), "temp_screenshot")
        os.makedirs(root, exist_ok=True)
        return root

    def _file_input_state(self):
        script = """
        const norm = text => String(text || '').replace(/\\s+/g, ' ').trim();
        const visible = el => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none';
        };
        const brief = el => {
          const rect = el.getBoundingClientRect();
          return {
            tag: el.tagName,
            type: el.getAttribute('type') || '',
            accept: el.getAttribute('accept') || '',
            id: el.id || '',
            className: String(el.className || ''),
            text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '').slice(0, 120),
            visible: visible(el),
            rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
          };
        };
        const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map(brief);
        const uploadish = Array.from(document.querySelectorAll('button,[role="button"],label,div,span'))
          .filter(el => {
            const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.className || '');
            return visible(el) && /上传|选择视频|点击上传|发布视频|拖拽|upload|select video/i.test(text);
          })
          .slice(0, 60)
          .map(brief);
        return {
          url: location.href,
          title: document.title,
          inputs,
          uploadish,
          bodyExcerpt: norm(document.body ? document.body.innerText : '').slice(0, 1800),
        };
        """
        try:
            return self.driver.execute_script(script) or {}
        except Exception as exc:
            return {"error": str(exc)}

    def _save_upload_debug_snapshot(self, label):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self._debug_dir(), f"douyin_{label}_{timestamp}")
        state = self._file_input_state()
        try:
            with open(f"{base}.json", "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"Could not write Douyin debug JSON: {exc}")
        try:
            self.driver.save_screenshot(f"{base}.png")
        except Exception as exc:
            print(f"Could not write Douyin debug screenshot: {exc}")
        try:
            html = self.driver.execute_script("return document.documentElement.outerHTML || '';")
            with open(f"{base}.html", "w", encoding="utf-8") as fh:
                fh.write(html)
        except Exception as exc:
            print(f"Could not write Douyin debug HTML: {exc}")
        print(f"Saved Douyin upload debug snapshot: {base}.*")
        return base, state

    def _upload_route_ready(self):
        state = self._file_input_state()
        body = state.get("bodyExcerpt", "") if isinstance(state, dict) else ""
        if state.get("inputs") or state.get("uploadish"):
            return True, state
        ready_terms = [
            "上传视频",
            "点击上传",
            "选择视频",
            "发布视频",
            "作品标题",
            "添加作品简介",
            "重新上传",
            "上传完成",
        ]
        loading_terms = [
            "加载中，请稍候",
            "加载中",
        ]
        if any(term in body for term in ready_terms) and not any(term in body for term in loading_terms):
            return True, state
        return False, state

    def _reload_upload_route(self, reason):
        print(f"Reloading Douyin upload route: {reason}")
        try:
            self.driver.execute_script("window.stop && window.stop();")
        except Exception:
            pass
        try:
            self.driver.execute_script("location.href = 'https://creator.douyin.com/creator-micro/content/upload';")
        except Exception:
            try:
                self.driver.get("https://creator.douyin.com/creator-micro/content/upload")
            except Exception:
                pass
        time.sleep(8)

    def _ensure_upload_route_ready(self, timeout=45, max_reloads=2):
        last_state = {}
        for attempt in range(max_reloads + 1):
            deadline = time.time() + timeout
            while time.time() < deadline:
                ready, state = self._upload_route_ready()
                last_state = state
                if ready:
                    return True
                body = state.get("bodyExcerpt", "") if isinstance(state, dict) else ""
                if "登录" in body and "加载中" not in body:
                    return True
                time.sleep(2)
            if attempt < max_reloads:
                body = last_state.get("bodyExcerpt", "") if isinstance(last_state, dict) else ""
                self._reload_upload_route(
                    f"upload controls did not render after {timeout}s; body excerpt: {body[:160]!r}"
                )
        body = last_state.get("bodyExcerpt", "") if isinstance(last_state, dict) else ""
        base, _ = self._save_upload_debug_snapshot("upload_route_not_ready")
        raise UploadInputMissingException(
            "Douyin upload route did not render upload controls. "
            f"Debug snapshot: {base}.*; page excerpt: {body[:500]!r}"
        )

    def _dismiss_upload_blockers(self):
        try:
            dismiss_alert(self.driver)
        except Exception:
            pass
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(0.3)
        except Exception:
            pass
        script = """
        const norm = text => String(text || '').replace(/\\s+/g, ' ').trim();
        const visible = el => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none'
            && style.pointerEvents !== 'none';
        };
        const texts = new Set(['我知道了', '知道了', '关闭', '取消', '暂不', '稍后再说']);
        const buttons = Array.from(document.querySelectorAll('button,[role="button"],.semi-modal-close,.semi-toast-close,svg'));
        let clicked = [];
        for (const el of buttons) {
          const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
          if (visible(el) && (texts.has(text) || /close|关闭/.test(String(el.className || '').toLowerCase()))) {
            try {
              el.click();
              clicked.push(text || String(el.className || '').slice(0, 80));
              if (clicked.length >= 3) break;
            } catch (_) {}
          }
        }
        return clicked;
        """
        try:
            clicked = self.driver.execute_script(script)
            if clicked:
                print(f"Dismissed possible Douyin upload blockers: {clicked}")
                time.sleep(1)
        except Exception:
            pass

    def _find_upload_input_js(self):
        script = """
        const visible = el => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none';
        };
        const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
        const scored = inputs.map((el, index) => {
          const accept = String(el.getAttribute('accept') || '').toLowerCase();
          const cls = String(el.className || '').toLowerCase();
          let score = 0;
          if (accept.includes('video')) score += 40;
          if (accept.includes('mp4')) score += 30;
          if (accept.includes('*')) score += 5;
          if (/video|upload|file|uploader/.test(cls)) score += 10;
          if (visible(el)) score += 5;
          return { el, score, index, accept, visible: visible(el) };
        }).sort((a, b) => b.score - a.score || a.index - b.index);
        if (!scored.length) return null;
        const best = scored[0].el;
        try { best.scrollIntoView({ block: 'center' }); } catch (_) {}
        return best;
        """
        try:
            return self.driver.execute_script(script)
        except Exception as exc:
            print(f"Douyin JS file input probe failed: {exc}")
            return None

    def _find_upload_input(self, timeout=8):
        deadline = time.time() + timeout
        css_selectors = [
            'input[type="file"][accept*="video"]',
            'input[type="file"][accept*="mp4"]',
            'input[type="file"]',
        ]
        while time.time() < deadline:
            input_element = self._find_upload_input_js()
            if input_element:
                return input_element
            for selector in css_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        return elements[0]
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def _click_upload_entry(self):
        script = """
        const norm = text => String(text || '').replace(/\\s+/g, ' ').trim();
        const visible = el => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none'
            && style.pointerEvents !== 'none';
        };
        const candidates = Array.from(document.querySelectorAll('button,[role="button"],label,div,span,a'))
          .filter(el => {
            const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.className || '');
            return visible(el) && /上传视频|点击上传|选择视频|发布视频|本地上传|拖拽|上传|upload|select video/i.test(text);
          })
          .map(el => {
            const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
            const cls = String(el.className || '');
            const rect = el.getBoundingClientRect();
            let score = 0;
            if (/上传视频|点击上传|选择视频|本地上传/.test(text)) score += 50;
            if (/上传|upload|uploader/i.test(cls)) score += 15;
            if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || el.tagName === 'LABEL') score += 10;
            score += Math.min(10, Math.round((rect.width * rect.height) / 20000));
            return { el, text, cls, score, rect };
          })
          .sort((a, b) => b.score - a.score);
        if (!candidates.length) return { ok: false };
        const item = candidates[0];
        try { item.el.scrollIntoView({ block: 'center' }); } catch (_) {}
        item.el.click();
        return {
          ok: true,
          text: item.text,
          className: item.cls.slice(0, 120),
          score: item.score,
          rect: { x: Math.round(item.rect.x), y: Math.round(item.rect.y), w: Math.round(item.rect.width), h: Math.round(item.rect.height) },
        };
        """
        try:
            result = self.driver.execute_script(script)
            if result and result.get("ok"):
                print(f"Clicked Douyin upload entry: {result}")
                time.sleep(2)
                return True
        except Exception as exc:
            print(f"Douyin upload entry click failed: {exc}")
        return self._click_any(
            [
                '//*[contains(normalize-space(),"上传视频")]',
                '//*[contains(normalize-space(),"点击上传")]',
                '//*[contains(normalize-space(),"选择视频")]',
                '//*[contains(normalize-space(),"本地上传")]',
                '//*[contains(normalize-space(),"上传")]/ancestor::button[1]',
                '//*[contains(normalize-space(),"上传")]',
            ],
            timeout=3,
        )

    def _send_file_to_input(self, video_input, path_mp4):
        try:
            video_input.send_keys(path_mp4)
            return
        except WebDriverException as exc:
            print(f"Douyin file input send_keys failed once; making input interactable and retrying: {exc}")
        self.driver.execute_script(
            """
            const el = arguments[0];
            el.removeAttribute('hidden');
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.opacity = '1';
            el.style.position = 'fixed';
            el.style.left = '20px';
            el.style.top = '20px';
            el.style.width = '400px';
            el.style.height = '40px';
            el.style.zIndex = '2147483647';
            """,
            video_input,
        )
        time.sleep(0.5)
        video_input.send_keys(path_mp4)

    def _resume_unpublished_draft_if_present(self, for_replacement=False):
        """Reuse Douyin's existing unpublished draft when the upload already exists.

        Douyin can leave a successful upload in a local/server draft if a later
        step fails. In that state the upload page shows "你还有上次未发布的视频".
        Starting a fresh upload wastes time and can create duplicate/stale
        drafts, so continue the draft before falling back to file upload.
        """
        body_text = self._body_text()
        prompt_present = "你还有上次未发布的视频" in body_text or "继续编辑" in body_text
        if not prompt_present:
            return False

        if for_replacement:
            print("Douyin unpublished draft prompt detected; opening draft to replace failed/stale media.")
        else:
            print("Douyin unpublished draft prompt detected; continuing existing draft.")
        # The SPA can enter the editor while a stale prompt snapshot is being
        # inspected. Poll the route and visible control together, not 3 serial
        # XPath waits against a modal which may no longer exist.
        deadline = time.monotonic() + 12
        clicked = False
        while time.monotonic() < deadline:
            state = self.driver.execute_script("""
                const visible = el => {
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                        && s.display !== 'none';
                };
                const button = Array.from(document.querySelectorAll('button,[role="button"],a,span'))
                    .find(el => visible(el) && el.textContent.trim() === '继续编辑');
                const editor = location.pathname.endsWith('/content/post/video');
                return {editor, button, prompt: (document.body?.innerText || '').includes('你还有上次未发布的视频')};
            """) or {}
            if state.get("button") and not clicked:
                clicked = self._safe_click(state["button"])
            elif state.get("editor"):
                return True
            elif not state.get("prompt") and not clicked:
                return False
            time.sleep(0.5)
        base, _ = self._save_upload_debug_snapshot("draft_resume_timeout")
        raise UploadInputMissingException(f"Douyin draft did not enter the editor; inspect {base}.*")

    def _allow_draft_reuse(self):
        options = publish_options(**self.metadata.get("_douyin_options", {}))
        expected = options["resume_sha256"]
        if expected:
            digest = hashlib.sha256()
            with open(self.path_mp4, "rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("Reviewed Douyin upload does not match this package's video")
            return True
        if os.environ.get("AUTOPUB_DOUYIN_REUSE_DRAFT", "0").lower() in {"1", "true", "yes", "on"}:
            raise ValueError("Unbound draft reuse disabled; provide the reviewed upload SHA-256 per job")
        return False

    def _wait_for_upload(self, upload_started_at=None):
        """Retry only one explicit failed upload, never the publication workflow."""
        watch = UploadWatch(time.monotonic(),
                            idle_seconds=int(os.environ.get("AUTOPUB_DOUYIN_UPLOAD_IDLE_TIMEOUT", "180")))
        grace = int(os.environ.get("AUTOPUB_DOUYIN_STALE_FAILURE_GRACE", "45"))
        retries = 0
        last_log = 0
        while True:
            body = self._body_text()
            gate = upload_gate(body)
            if gate:
                raise UploadFailedException(f"Douyin requires operator attention: {gate}")
            progress = upload_progress(body)
            now = time.monotonic()
            if now - last_log >= 30:
                print(f"Douyin upload progress: {json.dumps(progress, ensure_ascii=False)}")
                last_log = now
            if progress["status"] == "ready":
                print("Douyin native upload completion confirmed.")
                return
            if progress["status"] == "failed":
                if upload_started_at and time.time() - upload_started_at < grace:
                    time.sleep(5)
                    continue
                base, _ = self._save_upload_debug_snapshot("upload_failed")
                if retries == 0 and not getattr(self, "_submit_attempted", False):
                    retries += 1
                    print(f"Retrying failed media upload once, in the same editor; evidence={base}.*")
                    time.sleep(10)
                    upload_started_at = self._upload_video_file(self.path_mp4)
                    watch = UploadWatch(time.monotonic(), idle_seconds=watch.idle_seconds)
                    continue
                raise UploadFailedException(f"Douyin upload failed after bounded recovery; evidence={base}.*")
            reason = watch.observe(progress, now)
            if reason:
                base, _ = self._save_upload_debug_snapshot("upload_stalled")
                raise UploadFailedException(f"{reason}; no blind retry of pending upload; evidence={base}.*")
            time.sleep(5)

    def _set_content_label(self):
        options = publish_options(**self.metadata.get("_douyin_options", {}))
        if not options["content_label"]:
            return
        label = "内容由AI生成"
        current = self.driver.execute_script("""
          return Array.from(document.querySelectorAll('[class*="selectText-"]'))
            .some(e => e.getClientRects().length && e.textContent.trim() === arguments[0]);
        """, label)
        if current:
            return
        self._click_first(['//*[normalize-space(text())="请选择自主声明"]'], timeout=10)
        self._click_first(['//div[contains(@class,"semi-modal-content")]//label[.//span[normalize-space()="内容由AI生成"]]'], timeout=10)
        self._click_first(['//div[contains(@class,"semi-modal-content")]//button[normalize-space()="确定"]'], timeout=10)
        WebDriverWait(self.driver, 10).until(lambda d: d.execute_script("""
          return Array.from(document.querySelectorAll('[class*="selectText-"]'))
            .some(e => e.getClientRects().length && e.textContent.trim() === arguments[0]);
        """, label))
        print("Verified Douyin native declaration: 内容由AI生成")

    def _replace_existing_draft_video(self, path_mp4):
        """Replace a resumed Douyin draft instead of publishing stale uploaded media."""
        print("Douyin draft reuse is disabled; replacing the draft video with the requested file.")
        self._click_any(
            [
                '//*[normalize-space()="重新上传"]',
                '//*[contains(text(),"重新上传")]/ancestor::button[1]',
                '//*[contains(text(),"替换视频")]/ancestor::button[1]',
                '//*[contains(text(),"替换视频")]',
            ],
            timeout=8,
        )
        time.sleep(3)
        return self._upload_video_file(path_mp4)

    def _upload_video_file(self, path_mp4):
        print("Uploading video file to Douyin...")
        if not path_mp4 or not os.path.exists(path_mp4):
            raise FileNotFoundError(f"Douyin upload video file not found: {path_mp4}")
        bring_to_front(["抖音"])
        self._dismiss_upload_blockers()
        self._ensure_upload_route_ready(
            timeout=int(os.environ.get("AUTOPUB_DOUYIN_UPLOAD_READY_TIMEOUT", "45")),
            max_reloads=int(os.environ.get("AUTOPUB_DOUYIN_UPLOAD_READY_RELOADS", "2")),
        )
        video_input = self._find_upload_input(timeout=8)
        if not video_input:
            print("Douyin file input not immediately present; clicking upload area and retrying.")
            self._click_upload_entry()
            self._dismiss_upload_blockers()
            video_input = self._find_upload_input(timeout=20)
        if not video_input:
            base, state = self._save_upload_debug_snapshot("missing_upload_input")
            excerpt = (state.get("bodyExcerpt") or "")[:500] if isinstance(state, dict) else ""
            raise UploadInputMissingException(
                "Could not find Douyin upload <input type=file>. "
                f"Debug snapshot: {base}.*; page excerpt: {excerpt!r}"
            )
        self._send_file_to_input(video_input, path_mp4)
        time.sleep(5)
        return time.time()

    def _click_publish_button(self):
        if getattr(self, "_submit_attempted", False):
            raise PublishVerificationException("A publish click was already attempted; reconcile management first")
        # Mark before dispatch: even a lost CDP response can mean the click landed.
        self._submit_attempted = True
        self.publication_receipt = {
            "submission": "attempted", "publication_state": "unknown",
            "retry_safe": False, "observed_at": datetime.now().isoformat(timespec="seconds"),
        }
        script = """
        const norm = text => (text || '').replace(/\\s+/g, ' ').trim();
        const visible = el => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none'
            && style.pointerEvents !== 'none';
        };
        const candidates = Array.from(document.querySelectorAll('button,[role="button"]'))
          .filter(el => visible(el) && !el.disabled && !el.className.includes('disabled'))
          .map(el => ({ el, text: norm(el.innerText || el.textContent), rect: el.getBoundingClientRect() }))
          .filter(item => item.text === '发布' || item.text === '立即发布' || item.text === '确认发布');
        candidates.sort((a, b) => {
          const score = item => {
            let value = 0;
            if (item.text === '发布') value += 10;
            if (String(item.el.className || '').includes('primary')) value += 5;
            value += Math.min(5, Math.max(0, item.rect.top / 200));
            return value;
          };
          return score(b) - score(a);
        });
        if (!candidates.length) return { ok: false };
        candidates[0].el.scrollIntoView({ block: 'center' });
        candidates[0].el.click();
        return {
          ok: true,
          text: candidates[0].text,
          className: String(candidates[0].el.className || ''),
          top: candidates[0].rect.top
        };
        """
        try:
            result = self.driver.execute_script(script)
            if result and result.get("ok"):
                print(f"Clicked Douyin publish button: {result}")
                return
        except Exception as exc:
            raise PublishVerificationException("Publish click outcome unknown; no fallback click") from exc
        raise PublishVerificationException("No unambiguous publish control; inspect before retrying")

    def _click_publish_confirm_if_present(self):
        # Never click arbitrary page-wide 确定/确认 controls or repeat a dialog.
        key = self.driver.execute_script("""
          const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
          const dialogs = Array.from(document.querySelectorAll('[role="dialog"],.semi-modal-content'))
            .filter(e => visible(e) && /发布/.test(e.innerText) && !/添加声明/.test(e.innerText));
          for (const dialog of dialogs) {
            const buttons = Array.from(dialog.querySelectorAll('button')).filter(e => visible(e)
              && !e.disabled && ['确认发布','继续发布','确定','确认'].includes(e.innerText.trim()));
            if (buttons.length !== 1) continue;
            const key = dialog.innerText.trim();
            if (key === arguments[0]) return null;
            buttons[0].click(); return key;
          }
          return null;
        """, getattr(self, "_confirmed_dialog", ""))
        if key:
            self._confirmed_dialog = key
        return bool(key)

    def _wait_for_publish_submit_result(self, timeout=180):
        deadline = time.time() + timeout
        last_text = ""
        while time.time() < deadline:
            dismiss_alert(self.driver)
            if self._click_publish_confirm_if_present():
                print("Clicked Douyin publish confirmation dialog.")
                time.sleep(3)

            current_url = self.driver.current_url
            body_text = self._body_text()
            if body_text:
                last_text = body_text[:1000]
            outcome = submit_outcome(current_url, body_text)
            if outcome == "accepted":
                print("Douyin publish submit accepted by receipt or management navigation.")
                return True
            if outcome == "blocked":
                raise RuntimeError(f"Douyin publish submit failed or blocked. Page excerpt: {last_text!r}")
            time.sleep(5)

        raise PublishVerificationException(f"Timed out waiting for Douyin publish submit result. Page excerpt: {last_text!r}")

    def _set_input_value(self, element, text):
        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                const value = arguments[1];
                const proto = Object.getPrototypeOf(el);
                const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
                  || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
                  || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                if (descriptor && descriptor.set) {
                    descriptor.set.call(el, value);
                } else {
                    el.value = value;
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                element,
                text,
            )
            return
        except Exception:
            self.driver.execute_script(
                """
                const el = arguments[0];
                el.value = arguments[1];
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                element,
                text,
            )

    def _set_text(self, element, text):
        tag_name = ""
        try:
            tag_name = element.tag_name.lower()
        except Exception:
            pass
        if tag_name in ("input", "textarea"):
            self._set_input_value(element, text)
            return
        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                const value = arguments[1];
                el.focus();
                if (el.isContentEditable) {
                    el.innerText = value;
                } else {
                    el.textContent = value;
                }
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: value
                }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                element,
                text,
            )
        except Exception:
            self.driver.execute_script(
                """
                const el = arguments[0];
                el.textContent = arguments[1];
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                element,
                text,
            )

    def _add_topics(self, tags):
        if not tags:
            return False
        try:
            topic_input = self._find_first(
                [
                    '//input[contains(@placeholder,"话题")]',
                    '//div[@data-placeholder="添加话题" and @contenteditable="true"]',
                    '//div[contains(@class,"topic") and @contenteditable="true"]',
                    '//*[contains(text(),"话题")]/..//input',
                ],
                timeout=3,
                visible=False,
            )
        except Exception:
            return False
        for tag in tags:
            cleaned = tag.strip().lstrip("#")
            if not cleaned:
                continue
            try:
                topic_input.click()
                topic_input.send_keys(f"#{cleaned}")
                time.sleep(0.5)
                topic_input.send_keys(Keys.ENTER)
                time.sleep(0.5)
            except Exception:
                continue
        return True

    def wait_for_element_to_be_clickable(self, xpath, timeout=600):
        time.sleep(3)  # your actual implementation


    def publish(self):
        if getattr(self, "_submit_attempted", False):
            raise PublishVerificationException("Submission was already attempted; do not replay")
        if self.retry_count < 3:  # legacy adapter compatibility; no recursive whole-job retry
            try:
                driver = self.driver
                path_mp4 = self.path_mp4
                path_cover = self.path_cover
                metadata = self.metadata
                test = self.test

                print("Starting the publishing process on Douyin...")
                if not self._verified_editor():
                    safe_get(driver, "https://creator.douyin.com/creator-micro/content/upload", timeout=45, label="Douyin upload page")
                    time.sleep(1)
                    dismiss_alert(driver)
                    time.sleep(10)

                bring_to_front(["抖音"])  # This should be defined somewhere in your code
                close_extra_tabs(driver)

                allow_draft_reuse = self._allow_draft_reuse()
                resumed_draft = self._resume_unpublished_draft_if_present(for_replacement=not allow_draft_reuse)
                upload_started_at = None
                draft_upload_failed = upload_outcome(self._body_text()) == "failed"
                if draft_upload_failed:
                    print("Existing Douyin draft has a failed upload; reuploading inside the draft.")
                    upload_started_at = self._upload_video_file(path_mp4)
                elif (resumed_draft or upload_outcome(self._body_text()) == "ready") and not allow_draft_reuse:
                    upload_started_at = self._replace_existing_draft_video(path_mp4)
                elif allow_draft_reuse and (resumed_draft or upload_outcome(self._body_text()) == "ready"):
                    print("Using existing Douyin draft/upload; skipping video upload.")
                else:
                    upload_started_at = self._upload_video_file(path_mp4)

                self._wait_for_upload(upload_started_at)

                print("Skipping cover upload for Douyin.")
                time.sleep(2)

                 # Entering the title
                print("Entering the title...")
                title_input_element = self._find_first(
                    [
                        '//input[@placeholder="填写作品标题，为作品获得更多流量"]',
                        '//input[@placeholder="好的作品标题可获得更多浏览"]',
                        '//input[contains(@placeholder,"标题")]',
                        '//div[contains(@class,"title") or contains(@class,"Title")]//input',
                    ],
                    timeout=30,
                )
                time.sleep(1)
                title_text = (metadata.get("title") or "").strip()[:30]
                self._set_input_value(title_input_element, title_text)



                print("Entering video description...")
                description_input_element = self._find_first(
                    [
                        '//div[@data-placeholder="添加作品简介"]',
                        '//div[@contenteditable="true" and contains(@data-placeholder,"简介")]',
                        '//textarea[contains(@placeholder,"简介")]',
                        '//div[@contenteditable="true"]',
                    ],
                    timeout=30,
                )
                tags = [tag.strip().lstrip("#") for tag in metadata.get("tags", []) if tag and tag.strip()]
                # Douyin's separate topic widget is optional and can wedge the
                # browser on send_keys. Keep hashtags in the description, which
                # is enough for publishing and avoids blocking the queue.
                combined_tags = tags
                description_text = (metadata.get("long_description") or metadata.get("brief_description") or "").strip()
                tag_text = " ".join([f"#{tag}" for tag in combined_tags if tag])
                description_with_tags = f"{description_text} {tag_text}".strip()
                time.sleep(1)
                self._set_text(description_input_element, description_with_tags[:1000])
                actual = self.driver.execute_script("""
                  return {title: arguments[0].value,
                    description: arguments[1].value ?? arguments[1].innerText};
                """, title_input_element, description_input_element)
                normalize = lambda value: " ".join(str(value or "").replace("\u200b", "").split())
                if (normalize(actual.get("title")) != normalize(title_text)
                        or normalize(actual.get("description")) != normalize(description_with_tags[:1000])):
                    raise RuntimeError("Douyin title/description readback mismatch; not submitting")


                # Never invent a filming location or add unrelated engagement tags.
                self._set_content_label()


                

                # JavaScript code as a multi-line Python string
                script = """
                let elementsWithText = Array.from(document.querySelectorAll("div")).filter(el => el.textContent.includes('原创内容'));
                let targetSwitch;

                elementsWithText.forEach(el => {
                    let switchElement = el.parentElement.querySelector("input[type='checkbox'][role='switch']");
                    if (switchElement) {
                        targetSwitch = switchElement;
                    }
                });

                if (targetSwitch) {
                    // Return information about the switch to the Python context
                    return {
                        found: true,
                        currentState: targetSwitch.checked ? "ON" : "OFF"
                    };
                } else {
                    return {
                        found: false
                    };
                }
                """

                # Execute the script
                result = driver.execute_script(script)

                # Handle the result
                if result['found']:
                    print("Found '原创内容' switch.")
                    print("Current state of '原创内容' switch:", result['currentState'])

                    if result['currentState'] == "OFF":
                        toggle_script = """
                        let elementsWithText = Array.from(document.querySelectorAll("div")).filter(el => el.textContent.includes('原创内容'));
                        let targetSwitch;

                        elementsWithText.forEach(el => {
                            let switchElement = el.parentElement.querySelector("input[type='checkbox'][role='switch']");
                            if (switchElement) {
                                targetSwitch = switchElement;
                            }
                        });

                        if (targetSwitch) {
                            targetSwitch.click();
                        }
                        """
                        time.sleep(3)
                        driver.execute_script(toggle_script)
                        print("Enabled the '原创内容' switch.")
                else:
                    print("Could not find '原创内容' switch.")

                # Final steps for publishing
                if test:
                    print("Douyin test mode: prepared only; no final submit and not published.")
                    return False
                else:
                    user_input = "yes"
                if user_input == 'yes':
                    print("Publishing the video...")
                    time.sleep(3)
                    submitted_at = datetime.now()
                    self._click_publish_button()
                    self._wait_for_publish_submit_result(
                        timeout=int(os.environ.get("AUTOPUB_DOUYIN_SUBMIT_TIMEOUT", "180"))
                    )
                    try:
                        verify_publish_in_management(
                            driver,
                            DOUYIN_MANAGEMENT_URL,
                            metadata,
                            platform_name="Douyin",
                            timeout=int(os.environ.get("AUTOPUB_DOUYIN_VERIFY_TIMEOUT", "240")),
                            tab_xpaths=[
                                '//*[normalize-space()="审核中"]',
                                '//*[contains(normalize-space(),"审核中")]',
                                '//*[normalize-space()="已发布"]',
                                '//*[contains(normalize-space(),"已发布")]',
                                '//*[normalize-space()="全部作品"]',
                                '//*[contains(normalize-space(),"全部作品")]',
                            ],
                        )
                        self.publication_receipt = self._management_receipt(
                            title_text, description_with_tags[:1000], submitted_at)
                    except Exception as exc:
                        raise PublishVerificationException(
                            "Submit accepted, but management confirmation is pending; do not resubmit"
                        ) from exc
                    state = self.publication_receipt["publication_state"]
                    print(f"Douyin native submission verified; publication state: {state}")
                    if state in {"restricted", "rejected", "private"}:
                        raise PublishVerificationException(
                            f"Douyin native state is {state}; inspect reason, do not reupload")
                else:
                    print("Publishing cancelled by the user.")
                
                self.retry_count = 0  # reset retry count after successful execution
                return True
            except PublishVerificationException:
                print("Douyin publish verification failed after submit; not retrying to avoid duplicate uploads.")
                raise
            except UploadInputMissingException:
                print("Douyin upload input is missing; not retrying the whole publish flow blindly.")
                traceback.print_exc()
                self.retry_count = 0
                raise
            except Exception as e:
                print(f"An error occurred: {e}")
                traceback.print_exc()
                if getattr(self, "_submit_attempted", False):
                    raise PublishVerificationException(
                        "Failure after final-click barrier; inspect management, never replay the job"
                    ) from e
                # Upload-only recovery is bounded inside _wait_for_upload.
                # Form, authentication and transport ambiguity never restart a whole post.
                raise
        else:
            raise RuntimeError("Maximum retry attempts reached. Douyin process failed.")

# Rest of your code for initialization and running the publisher
def get_media_paths(catalog):
    path = pathlib.Path(catalog)
    path_mp4 = next((str(p) for p in path.glob('*.mp4')), None)
    path_cover = next((str(p) for p in path.glob('*') if p.suffix in ['.png', '.jpg']), None)
    return path_mp4, path_cover

if __name__ == "__main__":
    # Constants
    catalog_mp4 = r"/Users/lachlan/Documents/iProjects/auto-publish/videos"
    chrome_driver_path = "/user/local/bin/chromedriver"  # Change this to your Chromedriver path

    # Initialize Chrome options
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:5003")
    driver = webdriver.Chrome(options=options)

    # Get the video and cover paths
    path_mp4, path_cover = get_media_paths(catalog_mp4)
    if not path_mp4 or not path_cover:
        print("Video or cover file not found. Exiting...")
    else:
        print(f"Found video path: {path_mp4}")
        print(f"Found cover path: {path_cover}")

        # Metadata for the post
        metadata = {
            "title": "品味经典美味：超赞的烤鸡",
            "brief_description": "跟随我们的味蕾之旅，发现为何这款烤鸡让人赞不绝口！",
            "middle_description": "跟随我们的味蕾之旅，发现为何这款烤鸡让人赞不绝口！",
            "long_description": "跟随我们的味蕾之旅，发现为何这款烤鸡让人赞不绝口！",
            "tags": ["美食", "烤鸡", "推荐"]
        }

        # Create an instance of the DouyinPublisher
        pub_douyinlisher = DouyinPublisher(
            driver=driver,
            path_mp4=path_mp4,
            path_cover=path_cover,
            metadata=metadata
        )

        # Start publishing process
        pub_douyinlisher.publish()
