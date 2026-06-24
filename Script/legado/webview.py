from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class PlaywrightWebView:
    def __init__(self, base_dir: str | Path, source_id: str, text_source: bool = True):
        self.base_dir = Path(base_dir)
        self.source_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)
        self.text_source = text_source
        self.profile_dir = self.base_dir / "Dashboard" / "data" / "legado" / "state" / "profiles" / self.source_id
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def fetch(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        script: Optional[str] = None,
        delay_ms: int = 900,
        timeout_ms: int = 60000,
        bridge_handlers: Optional[Dict[str, Callable[..., Any]]] = None,
        cookie_state: Optional[Dict[str, str]] = None,
    ) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(f"Playwright is not available for Legado WebView: {exc}") from exc

        cookies = cookie_state if cookie_state is not None else {}
        with sync_playwright() as p:
            active_headers = self._headers_with_cookies(headers or {}, cookies)
            context = self._launch_context(p, active_headers)
            try:
                page = context.new_page()
                if bridge_handlers is not None:
                    self._install_bridge(page, bridge_handlers)
                if self.text_source:
                    page.route("**/*", lambda route: route.abort() if route.request.resource_type == "image" else route.continue_())
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if delay_ms > 0:
                    page.wait_for_timeout(delay_ms)
                js = script or "document.documentElement.outerHTML"
                result = self._evaluate_with_retry(page, js)
                self._store_context_cookies(context, cookies)
                return "" if result is None else str(result)
            finally:
                context.close()

    def _headers_with_cookies(self, headers: Dict[str, str], cookie_state: Dict[str, str]) -> Dict[str, str]:
        merged = dict(headers or {})
        if cookie_state and not any(k.lower() == "cookie" for k in merged):
            merged["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_state.items() if v not in (None, ""))
        return merged

    def _store_context_cookies(self, context, cookie_state: Dict[str, str]) -> None:
        if cookie_state is None:
            return
        try:
            for cookie in context.cookies():
                name = cookie.get("name")
                value = cookie.get("value")
                if name and value is not None:
                    cookie_state[name] = value
        except Exception:
            return

    def _install_bridge(self, page, handlers: Dict[str, Callable[..., Any]]) -> None:
        def request(name, args):
            handler = handlers.get(str(name))
            if not handler:
                raise RuntimeError(f"Unsupported WebJS bridge call: {name}")
            return handler(*(args or []))

        page.expose_function("__legadoBridgeRequest", request)
        page.add_init_script(self.bridge_script())

    @staticmethod
    def bridge_script() -> str:
        return """
            (() => {
              if (window.__legadoBridgeInstalled) return;
              window.__legadoBridgeInstalled = true;
              const call = (name, args) => window.__legadoBridgeRequest(name, args || []);
              window.run = (jsCode) => call('run', [String(jsCode)]);
              window.ajaxAwait = (...args) => call('ajaxAwait', args.map(String));
              window.connectAwait = (...args) => call('connectAwait', args.map(String));
              window.getAwait = (...args) => call('getAwait', args.map(String));
              window.headAwait = (...args) => call('headAwait', args.map(String));
              window.postAwait = (...args) => call('postAwait', args.map(String));
              window.webViewAwait = (...args) => call('webViewAwait', args.map(String));
              window.webViewGetSourceAwait = (...args) => call('webViewGetSourceAwait', args.map(String));
              window.webViewGetOverrideUrlAwait = (...args) => call('webViewGetOverrideUrlAwait', args.map(String));
              window.downloadFileAwait = (url) => call('downloadFileAwait', [String(url)]);
              window.readTxtFileAwait = (path) => call('readTxtFileAwait', [String(path)]);
              window.importScriptAwait = (path) => call('importScriptAwait', [String(path)]);
              window.startBrowserAwait = (...args) => call('startBrowserAwait', args.map(String));
              window.upLoginData = (...args) => call('upLoginData', args.map(String));
              window.setContent = (...args) => call('setContent', args.map(String));
              window.getStringAwait = (rule) => call('getStringAwait', [String(rule), document.documentElement.outerHTML]);
            })();
        """

    def _launch_context(self, playwright, headers: Dict[str, str]):
        executable = None
        for candidate in [shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chromium-browser")]:
            if candidate:
                executable = candidate
                break
        kwargs = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-setuid-sandbox"],
            "viewport": {"width": 390, "height": 844},
            "is_mobile": True,
            "has_touch": True,
            "locale": "zh-CN",
            "extra_http_headers": headers,
        }
        ua = headers.get("User-Agent") or headers.get("user-agent")
        if ua:
            kwargs["user_agent"] = ua
        if executable:
            kwargs["executable_path"] = executable
        return playwright.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)

    def _evaluate_with_retry(self, page, script: str):
        last = None
        for attempt in range(31):
            try:
                value = page.evaluate(script)
                if value not in (None, ""):
                    return value
                last = value
            except Exception as exc:
                last = exc
            page.wait_for_timeout(min(1000, 200 * (attempt + 1)))
        if isinstance(last, Exception):
            raise last
        return last
