from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin
from http.cookies import SimpleCookie
import re

from bs4 import BeautifulSoup

from legado.analyze_url import AnalyzeUrl
from legado.models import BookSource, classify_source, source_plugin_id
from legado.rule_engine import LegadoRuleEngine, UnsupportedRuleError
from legado.rhino_bridge import RhinoBridge, RhinoBridgeError
from legado.state_store import LegadoStateStore
from legado.webview import PlaywrightWebView
from plugins.base_plugin import BasePlugin, normalize_chapter_order


class LegadoHttpResponse(dict):
    def __init__(self, body="", status_code=200, headers=None, url=""):
        headers = dict(headers or {})
        super().__init__(body=body, statusCode=status_code, code=status_code, headers=headers, url=url)
        self.body = body
        self.statusCode = status_code
        self.code = status_code
        self.headers = headers
        self.url = url

    def bodyString(self):
        return self.body

    def header(self, key, default=""):
        for name, value in self.headers.items():
            if str(name).lower() == str(key).lower():
                return value
        return default

    def __str__(self):
        return self.body



class LegadoPlugin(BasePlugin):
    def __init__(self, source_record: dict, base_dir: str | None = None):
        self.source = BookSource.from_dict(source_record)
        self.base_dir = base_dir
        self.classification = source_record.get("_classification") or classify_source(self.source)
        self._source_id = source_record.get("_plugin_id") or source_plugin_id(self.source)
        self.state_store = LegadoStateStore(base_dir) if base_dir else None
        self._state_name = f"sources/{re.sub(r'[^A-Za-z0-9_.-]+', '_', self._source_id)}.json"
        loaded_state = self.state_store.load_json(self._state_name) if self.state_store else {}
        self.rhino = RhinoBridge(base_dir) if base_dir and self.classification.get("needs_js") else None
        self.cookie_state = {}
        self.cookie_state.update(self._source_header_cookies())
        self.cookie_state.update(dict(loaded_state.get("cookieState") or {}))
        self.cookie_state.update(self._configured_login_cookies(source_record))
        self.source_state = dict(loaded_state.get("sourceState") or {})
        self.cache_state = dict(loaded_state.get("cacheState") or {})
        self.book_state = dict(loaded_state.get("bookState") or {})
        self.chapter_state = dict(loaded_state.get("chapterState") or {})
        if self.rhino:
            self.rhino.cookie_state = dict(self.cookie_state)
            self.rhino.source_state = dict(self.source_state)
            self.rhino.cache_state = dict(self.cache_state)
            self.rhino.book_state = dict(self.book_state)
            self.rhino.chapter_state = dict(self.chapter_state)
        if self.cookie_state and self.state_store:
            self._save_state()

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def source_name(self) -> str:
        return self.source.name

    @property
    def supported_now(self) -> bool:
        if self.classification.get("needs_js") and not (self.rhino and self.rhino.available):
            return False
        if self.classification.get("needs_webview") and not self.base_dir:
            return False
        return self.classification.get("support_level") in {"native", "webview", "rhino", "partial"}

    def search(self, keyword: str) -> list:
        self._require_native()
        if not self.source.searchUrl or not self.source.ruleSearch.bookList:
            return []
        request = self._analyze_url(self.source.searchUrl, keyword=keyword, key=keyword, page=1)
        html = self._fetch(request)
        engine = self._engine(request.url)
        items = engine.get_elements(html, self.source.ruleSearch.bookList, base_url=request.url)
        out = []
        for item in items:
            book_url = engine.get_string(item, self.source.ruleSearch.bookUrl, base_url=request.url)
            cover_url = engine.get_string(item, self.source.ruleSearch.coverUrl, base_url=request.url)
            out.append({
                "title": engine.get_string(item, self.source.ruleSearch.name, base_url=request.url),
                "author": engine.get_string(item, self.source.ruleSearch.author, base_url=request.url),
                "description": engine.get_string(item, self.source.ruleSearch.intro, base_url=request.url),
                "kind": engine.get_string(item, self.source.ruleSearch.kind, base_url=request.url),
                "last_chapter": engine.get_string(item, self.source.ruleSearch.lastChapter, base_url=request.url),
                "update_time": engine.get_string(item, self.source.ruleSearch.updateTime, base_url=request.url),
                "word_count": engine.get_string(item, self.source.ruleSearch.wordCount, base_url=request.url),
                "cover_url": self._decode_cover_url(cover_url, request.url),
                "url": urljoin(request.url, book_url) if book_url else "",
                "source_id": self.source_id,
                "source_name": self.source_name,
            })
        self._save_state()
        return [item for item in out if item.get("title") or item.get("url")]

    def get_metadata(self, novel_url: str) -> dict:
        self._require_native()
        self._set_book_state({"bookUrl": novel_url, "tocUrl": novel_url})
        html = self._fetch_url(novel_url)
        engine = self._engine(novel_url)
        rule = self.source.ruleBookInfo
        content = self._apply_book_info_init(html, engine, rule.init, novel_url)
        cover_url = engine.get_string(content, rule.coverUrl, base_url=novel_url)
        metadata = {
            "title": engine.get_string(content, rule.name, base_url=novel_url),
            "author": engine.get_string(content, rule.author, base_url=novel_url),
            "description": engine.get_string(content, rule.intro, base_url=novel_url),
            "kind": ",".join(engine.get_string_list(content, rule.kind, base_url=novel_url)),
            "last_chapter": engine.get_string(content, rule.lastChapter, base_url=novel_url),
            "update_time": engine.get_string(content, rule.updateTime, base_url=novel_url),
            "word_count": engine.get_string(content, rule.wordCount, base_url=novel_url),
            "cover_url": self._decode_cover_url(cover_url, novel_url),
            "toc_url": engine.get_string(content, rule.tocUrl, base_url=novel_url),
            "source_url": novel_url,
            "source_id": self.source_id,
            "source_name": self.source_name,
        }
        if not metadata["title"]:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title:
                metadata["title"] = soup.title.get_text(" ", strip=True)
        self._set_book_state(metadata)
        self._save_state()
        return {k: v for k, v in metadata.items() if v not in (None, "")}

    def get_toc(self, novel_url: str) -> list:
        self._require_native()
        self._set_book_state({"bookUrl": novel_url, "tocUrl": novel_url})
        self._run_pre_update_js(novel_url)
        info = self.get_metadata(novel_url) if self.source.ruleBookInfo.tocUrl else {}
        toc_url = info.get("toc_url") or novel_url
        chapters = []
        seen_chapters = set()
        seen_pages = set()
        page_urls = [toc_url]
        rule = self.source.ruleToc
        while page_urls and len(seen_pages) < 12:
            page_url = page_urls.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            html = self._fetch_url(page_url)
            page_chapters, next_urls = self._parse_toc_page(html, page_url)
            for chapter in page_chapters:
                if chapter["url"] in seen_chapters:
                    continue
                seen_chapters.add(chapter["url"])
                chapters.append(chapter)
            for next_url in next_urls:
                if next_url and next_url not in seen_pages and next_url not in page_urls:
                    page_urls.append(next_url)
            if not rule.nextTocUrl:
                break
        chapters = self._apply_toc_format_js(chapters)
        self._save_state()
        return normalize_chapter_order(chapters)

    def get_chapter(self, chapter_url: str) -> str:
        self._require_native()
        self._set_chapter_state({"url": chapter_url})
        rule = self.source.ruleContent
        parts = []
        seen_pages = set()
        page_urls = [chapter_url]
        while page_urls and len(seen_pages) < 8:
            page_url = page_urls.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            html = self._fetch_content_url(page_url)
            content, next_urls = self._parse_content_page(html, page_url)
            if content.strip():
                parts.append(content.strip())
            for next_url in next_urls:
                if next_url and next_url not in seen_pages and next_url not in page_urls:
                    page_urls.append(next_url)
            if not rule.nextContentUrl:
                break
        text = "\n\n".join(parts)
        if rule.replaceRegex:
            try:
                text = self._engine(chapter_url).get_string(text, "all" + rule.replaceRegex, base_url=chapter_url)
            except Exception:
                pass
        self._save_state()
        return text

    def _apply_book_info_init(self, html: str, engine: LegadoRuleEngine, init_rule: str | None, base_url: str):
        if not init_rule:
            return html
        values = engine.get_elements(html, init_rule, base_url=base_url)
        return values[0] if values else html

    def _run_pre_update_js(self, base_url: str) -> None:
        rule = self.source.ruleToc.preUpdateJs
        if not rule:
            return
        if not self.rhino:
            raise UnsupportedRuleError("preUpdateJs requires Rhino")
        self.rhino.eval(str(rule), bindings={"baseUrl": base_url}, scope_key=self.source_id, js_lib=self.source.jsLib or "")
        self._save_state()

    def _parse_toc_page(self, html: str, toc_url: str):
        engine = self._engine(toc_url)
        rule = self.source.ruleToc
        items = engine.get_elements(html, rule.chapterList, base_url=toc_url) if rule.chapterList else []
        chapters = []
        for item in items:
            title = engine.get_string(item, rule.chapterName or "text", base_url=toc_url)
            href = engine.get_string(item, rule.chapterUrl or "href", base_url=toc_url)
            if not title or not href:
                continue
            chapters.append({"title": title, "url": urljoin(toc_url, href)})
        next_urls = []
        if rule.nextTocUrl:
            next_urls = [urljoin(toc_url, href) for href in engine.get_string_list(html, rule.nextTocUrl, base_url=toc_url)]
            next_urls = [url for url in next_urls if url and url != toc_url]
        return chapters, next_urls

    def _apply_toc_format_js(self, chapters: list) -> list:
        rule = self.source.ruleToc.formatJs
        if not rule:
            return chapters
        if not self.rhino:
            raise UnsupportedRuleError("formatJs requires Rhino")
        for index, chapter in enumerate(chapters, start=1):
            self._set_chapter_state(chapter)
            value = self.rhino.eval(
                str(rule),
                bindings={"index": index, "chapter": chapter, "title": chapter.get("title", ""), "gInt": 0},
                scope_key=self.source_id,
                js_lib=self.source.jsLib or "",
            )
            if value not in (None, ""):
                chapter["title"] = str(value)
        self._save_state()
        return chapters

    def _parse_content_page(self, html: str, page_url: str):
        self._set_chapter_state({"url": page_url})
        engine = self._engine(page_url)
        rule = self.source.ruleContent
        parts = engine.get_string_list(html, rule.content, base_url=page_url) if rule.content else []
        sub_content = engine.get_string(html, rule.subContent, base_url=page_url) if rule.subContent else ""
        if sub_content.strip():
            if sub_content.strip().lower().startswith(("http://", "https://")):
                sub_content = self._fetch_url(sub_content.strip())
            parts.append(sub_content)
        text = "\n\n".join(part.strip() for part in parts if part and part.strip())
        title = engine.get_string(html, rule.title, base_url=page_url) if rule.title else ""
        if title:
            self._set_chapter_state({"url": page_url, "title": title.strip(), "name": title.strip()})
            text = f"{title.strip()}\n\n{text}" if text else title.strip()
        next_urls = []
        if rule.nextContentUrl:
            next_urls = [urljoin(page_url, href) for href in engine.get_string_list(html, rule.nextContentUrl, base_url=page_url)]
            next_urls = [url for url in next_urls if url and url != page_url]
        return text, next_urls

    def _require_native(self):
        if not self.supported_now:
            raise UnsupportedRuleError(
                f"Legado source {self.source_name} requires {self.classification.get('support_level')} runtime"
            )

    def _fetch_url(self, url: str) -> str:
        request = self._analyze_url(url)
        return self._fetch(request)

    def _fetch_content_url(self, url: str) -> str:
        request = self._analyze_url(url)
        rule = self.source.ruleContent
        if rule.webJs or rule.sourceRegex:
            request.webview = True
        if rule.webJs:
            request.web_js = rule.webJs
        body = self._fetch(request)
        if rule.sourceRegex:
            extracted = self._extract_source_regex(body, request.url, rule.sourceRegex)
            return extracted if extracted or not body else body
        return body

    def _extract_source_regex(self, body: str, url: str, pattern: str) -> str:
        if not pattern:
            return body or ""
        try:
            match = re.search(pattern, body or url or "", re.S)
        except re.error:
            return ""
        if not match:
            return ""
        if match.lastindex:
            return next((group for group in match.groups() if group), "")
        return match.group(0)

    def _analyze_url(self, url_rule: str, **values):
        return AnalyzeUrl(
            self.source,
            self.source.bookSourceUrl,
            rhino=self.rhino,
            scope_key=self.source_id,
            js_lib=self.source.jsLib or "",
        ).build(url_rule, **values)

    def _engine(self, base_url: str):
        return LegadoRuleEngine(
            base_url,
            rhino=self.rhino,
            bindings={
                "tag": self.source_name,
                "baseUrl": base_url,
                "sourceState": self.source_state,
                "bookState": self.book_state,
                "chapterState": self.chapter_state,
            },
            scope_key=self.source_id,
            js_lib=self.source.jsLib or "",
        )

    def _webjs_handlers(self, base_url: str):
        def ajax(url, *args):
            request = self._analyze_url(str(url))
            return self._fetch(request)

        def request_object(url, method="GET", body=None):
            request = self._analyze_url(str(url))
            request.method = method
            if body is not None:
                request.body = str(body)
            return self._fetch_response(request)

        def get_string(rule, html=""):
            return self._engine(base_url).get_string(str(html), str(rule), base_url=base_url)

        def run(js_code):
            if not self.rhino:
                raise UnsupportedRuleError("WebJS run requires Rhino")
            result = self.rhino.eval(str(js_code), bindings={"baseUrl": base_url}, scope_key=self.source_id, js_lib=self.source.jsLib or "")
            self._save_state()
            return result

        def post(url, body="", *args):
            return request_object(url, "POST", body)

        def webview_extract(html="", url="", js="", regex="", *args):
            return self._webview_extract(str(html or ""), str(url or base_url), str(js or ""), str(regex or ""), override=False)

        def webview_override(html="", url="", js="", regex="", *args):
            return self._webview_extract(str(html or ""), str(url or base_url), str(js or ""), str(regex or ""), override=True)

        def start_browser(url="", title="", *args):
            url = str(url or "")
            self.source_state["lastBrowserUrl"] = url
            if title:
                self.source_state["lastBrowserTitle"] = str(title)
            self._save_state()
            if url.startswith(("http://", "https://")):
                return ajax(url)
            return url

        def up_login_data(*args):
            values = [str(arg) for arg in args if arg not in (None, "")]
            if values:
                self.source_state["loginData"] = values[-1]
                for value in values:
                    if "=" in value:
                        self.set_login_cookies(value, save=False)
            self._save_state()
            return True

        def set_content(content="", *args):
            self.source_state["content"] = str(content or "")
            self._save_state()
            return self.source_state["content"]

        return {
            "ajaxAwait": ajax,
            "connectAwait": lambda url, *args: request_object(url),
            "getAwait": lambda url, *args: request_object(url),
            "headAwait": lambda url, *args: request_object(url, "HEAD"),
            "postAwait": post,
            "webViewAwait": ajax,
            "webViewGetSourceAwait": webview_extract,
            "webViewGetOverrideUrlAwait": webview_override,
            "getStringAwait": get_string,
            "downloadFileAwait": lambda url, *args: self._download_script_file(str(url)),
            "readTxtFileAwait": lambda path, *args: self._read_text_file(str(path)),
            "importScriptAwait": lambda path, *args: self._import_script(str(path)),
            "startBrowserAwait": start_browser,
            "upLoginData": up_login_data,
            "setContent": set_content,
            "run": run,
        }

    def _webview_extract(self, html: str, url: str, js: str, pattern: str, override: bool = False) -> str:
        body = html
        if not body and url:
            request = self._analyze_url(url)
            request.webview = True
            request.web_js = js or "document.documentElement.outerHTML"
            body = self._fetch(request)
        if js and body and js != "document.documentElement.outerHTML":
            # When WebJS supplies an HTML string, Playwright has already run in the caller.
            # Keep regex extraction deterministic instead of evaluating arbitrary JS twice.
            pass
        if not pattern:
            return body or ""
        try:
            match = re.search(pattern, body or url or "", re.S)
        except re.error:
            return ""
        if not match:
            return ""
        if match.lastindex:
            return next((group for group in match.groups() if group), "")
        return match.group(0)

    def _script_cache_key(self, value: str) -> str:
        return "file:" + hashlib.md5(str(value).encode("utf-8")).hexdigest()[8:24]

    def _import_script(self, path: str) -> str:
        content = self._cache_file(path) if path.startswith(("http://", "https://")) else self._read_text_file(path)
        if not content.strip():
            raise UnsupportedRuleError(f"importScript returned empty content: {path}")
        return content

    def _cache_file(self, url: str) -> str:
        key = self._script_cache_key(url)
        cached = self.cache_state.get(key)
        if cached:
            return str(cached)
        request = self._analyze_url(url)
        response = self._fetch_response(request)
        self.cache_state[key] = response.body
        self._save_state()
        return response.body

    def _download_script_file(self, url: str) -> str:
        key = self._script_cache_key(url)
        if key not in self.cache_state:
            self.cache_state[key] = self._cache_file(url)
            self._save_state()
        return "cache://" + key.split(":", 1)[1]

    def _read_text_file(self, path: str) -> str:
        if path.startswith("cache://"):
            return str(self.cache_state.get("file:" + path[8:], ""))
        if not self.base_dir:
            return ""
        root = Path(self.base_dir).resolve()
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise UnsupportedRuleError("readTxtFile path is outside base_dir")
        if not target.exists() or not target.is_file():
            return ""
        return target.read_text(encoding="utf-8")

    def set_login_cookies(self, cookies, save: bool = True) -> dict:
        parsed = self._parse_cookie_value(cookies)
        self.cookie_state.update(parsed)
        if self.rhino:
            self.rhino.cookie_state.update(parsed)
        if save:
            self._save_state()
        return dict(self.cookie_state)

    def clear_login_cookies(self, keys=None) -> None:
        if keys is None:
            self.cookie_state.clear()
            if self.rhino:
                self.rhino.cookie_state.clear()
        else:
            for key in keys:
                self.cookie_state.pop(str(key), None)
                if self.rhino:
                    self.rhino.cookie_state.pop(str(key), None)
        self._save_state()

    def login(self, wait_ms: int | None = None, script: str | None = None, login_data: dict | None = None) -> bool:
        ui_data = self._login_data_from_ui(login_data)
        if ui_data:
            self._store_login_info(ui_data)
        if not self.source.loginUrl:
            self._save_state()
            return self.check_login()
        login_rule = str(self.source.loginUrl or "").strip()
        js_code = self._unwrap_js(login_rule)
        if js_code is not None or (self.source.loginUi and "function login" in login_rule):
            if not self.rhino:
                raise UnsupportedRuleError("loginUrl JS requires Rhino")
            code = js_code if js_code is not None else login_rule
            if "function login" in code:
                code = code + "\nif (typeof login == 'function') { login.apply(this); }"
            self._eval_login_js(code, ui_data, is_long_click=False)
        else:
            request = self._analyze_url(self.source.loginUrl)
            if self.source.loginUi or request.webview or request.web_js or script:
                request.webview = True
                if script:
                    request.web_js = script
                elif not request.web_js:
                    request.web_js = "document.documentElement.outerHTML"
                if wait_ms is not None:
                    request.webview_delay_ms = int(wait_ms)
                self._fetch(request)
            else:
                self._fetch_response(request)
        ui_js = self._unwrap_js(str(self.source.loginUi or "").strip())
        if ui_js and self.rhino:
            self.rhino.eval(ui_js, bindings={"baseUrl": self.source.loginUrl or self.source.bookSourceUrl, "result": ui_data}, scope_key=self.source_id, js_lib=self.source.jsLib or "")
        self._save_state()
        return self.check_login()



    def run_login_action(self, action_or_name: str, login_data: dict | None = None, long_click: bool = False):
        action = self._resolve_login_action(action_or_name)
        if not action:
            return None
        if action.startswith(("http://", "https://")):
            self.source_state["lastBrowserUrl"] = action
            if self.rhino:
                self.rhino.source_state.update(self.source_state)
            self._save_state()
            return action
        if not self.source.loginUrl:
            raise UnsupportedRuleError("login action requires loginUrl JS")
        login_rule = str(self.source.loginUrl or "").strip()
        js_code = self._unwrap_js(login_rule)
        code = (js_code if js_code is not None else login_rule) + "\n" + action
        ui_data = self._login_data_from_ui(login_data)
        if ui_data:
            self._store_login_info(ui_data)
        result = self._eval_login_js(code, ui_data, is_long_click=long_click)
        self._save_state()
        return result

    def _resolve_login_action(self, action_or_name: str) -> str:
        value = str(action_or_name or "").strip()
        if not value:
            return ""
        for row in self._parse_login_ui():
            if str(row.get("name") or "") == value and row.get("action"):
                return str(row.get("action") or "")
        return value

    def _eval_login_js(self, code: str, ui_data: dict, is_long_click: bool = False):
        if not self.rhino:
            raise UnsupportedRuleError("login JS requires Rhino")
        return self.rhino.eval(
            code,
            bindings={
                "baseUrl": self.source.bookSourceUrl,
                "result": ui_data,
                "loginData": ui_data,
                "isLongClick": bool(is_long_click),
            },
            scope_key=self.source_id,
            js_lib=self.source.jsLib or "",
        )

    def _unwrap_js(self, value: str) -> str | None:
        value = (value or "").strip()
        if value.startswith("@js:"):
            return value[4:]
        if value.startswith("<js>") and value.endswith("</js>"):
            return value[4:-5]
        return None

    def _parse_login_ui(self) -> list:
        raw = str(self.source.loginUi or "").strip()
        if not raw or self._unwrap_js(raw) is not None:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if isinstance(data, dict):
            data = [data]
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _login_data_from_ui(self, overrides: dict | None = None) -> dict:
        data = self._stored_login_info()
        for row in self._parse_login_ui():
            row_type = str(row.get("type") or "text")
            name = str(row.get("name") or "").strip()
            if not name or row_type == "button":
                continue
            if name in data:
                continue
            default = row.get("default")
            chars = row.get("chars")
            if default in (None, "") and isinstance(chars, list) and chars:
                default = chars[0]
            data[name] = "" if default is None else str(default)
        ui_data = self._login_ui_data_from_runtime()
        if ui_data:
            data.update(ui_data)
        if overrides:
            data.update({str(k): str(v) for k, v in overrides.items() if v is not None})
        return data

    def _login_ui_data_from_runtime(self) -> dict:
        raw = None
        java_state = self.cache_state.get("javaState")
        if isinstance(java_state, dict):
            raw = java_state.get("loginUiData")
        if raw is None:
            raw = self.source_state.get("loginUiData")
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items() if v is not None}
        if raw:
            try:
                parsed = json.loads(str(raw))
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items() if v is not None}
            except Exception:
                pass
        return {}

    def _stored_login_info(self) -> dict:
        raw = self.source_state.get("loginInfo")
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if raw:
            try:
                data = json.loads(str(raw))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if v is not None}
            except Exception:
                pass
        out = {}
        for key, value in self.source_state.items():
            if str(key).startswith("loginInfo:"):
                out[str(key)[10:]] = str(value)
        return out

    def _store_login_info(self, data: dict) -> None:
        normalized = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
        self.source_state["loginInfo"] = json.dumps(normalized, ensure_ascii=False)
        for key, value in normalized.items():
            self.source_state[f"loginInfo:{key}"] = value
        if self.rhino:
            self.rhino.source_state.update(self.source_state)

    def check_login(self) -> bool:
        rule = self.source.loginCheckJs
        if not rule:
            return bool(self.cookie_state)
        if not self.rhino:
            raise UnsupportedRuleError("loginCheckJs requires Rhino")
        result = self.rhino.eval(str(rule), bindings={"baseUrl": self.source.bookSourceUrl}, scope_key=self.source_id, js_lib=self.source.jsLib or "")
        self._save_state()
        return str(result).lower() not in {"", "0", "false", "none", "null"}

    def _source_header_cookies(self) -> dict:
        header = self.source.header
        if not header:
            return {}
        try:
            data = __import__("json").loads(header)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        for key, value in data.items():
            if str(key).lower() == "cookie":
                return self._parse_cookie_value(value)
        return {}

    def _configured_login_cookies(self, source_record: dict) -> dict:
        cookies = {}
        for key in ("loginCookies", "loginCookie", "cookies", "cookie"):
            if source_record.get(key):
                cookies.update(self._parse_cookie_value(source_record.get(key)))
        cookies.update(self._cookies_from_file())
        return cookies

    def _cookies_from_file(self) -> dict:
        if not self.base_dir:
            return {}
        path = Path(self.base_dir) / "Dashboard" / "data" / "legado" / "cookies.json"
        if not path.exists():
            return {}
        try:
            data = __import__("json").loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        keys = [self.source_id, self.source.bookSourceUrl, self.source.bookSourceName, self.source.name]
        for key in keys:
            if key and isinstance(data, dict) and key in data:
                return self._parse_cookie_value(data[key])
        return {}

    def _parse_cookie_value(self, value) -> dict:
        if not value:
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items() if v not in (None, "")}
        cookie = SimpleCookie()
        try:
            cookie.load(str(value))
            return {key: morsel.value for key, morsel in cookie.items()}
        except Exception:
            return {}

    def _set_book_state(self, values: dict | None) -> None:
        if not values:
            return
        mapping = {
            "title": "name",
            "source_url": "bookUrl",
            "toc_url": "tocUrl",
            "description": "intro",
        }
        for key, value in dict(values).items():
            if value in (None, ""):
                continue
            self.book_state[str(key)] = value
            if key in mapping:
                self.book_state[mapping[key]] = value
        if self.rhino:
            self.rhino.book_state.update(self.book_state)

    def _set_chapter_state(self, values: dict | None) -> None:
        if not values:
            return
        mapping = {"title": "name"}
        for key, value in dict(values).items():
            if value in (None, ""):
                continue
            self.chapter_state[str(key)] = value
            if key in mapping:
                self.chapter_state[mapping[key]] = value
        if self.rhino:
            self.rhino.chapter_state.update(self.chapter_state)

    def _sync_from_rhino(self) -> None:
        if not self.rhino:
            return
        self.cookie_state = dict(self.rhino.cookie_state or {})
        self.source_state = dict(self.rhino.source_state or {})
        self.cache_state = dict(self.rhino.cache_state or {})
        self.book_state = dict(self.rhino.book_state or {})
        self.chapter_state = dict(self.rhino.chapter_state or {})

    def _save_state(self) -> None:
        if not self.state_store:
            return
        self._sync_from_rhino()
        self.state_store.save_json(self._state_name, {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "cookieState": self.cookie_state,
            "sourceState": self.source_state,
            "cacheState": self.cache_state,
            "bookState": self.book_state,
            "chapterState": self.chapter_state,
        })

    def _cookies(self):
        return self.rhino.cookie_state if self.rhino else self.cookie_state

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies().items() if v not in (None, ""))

    def _headers_with_cookies(self, headers: dict) -> dict:
        merged = dict(headers or {})
        if not any(k.lower() == "cookie" for k in merged):
            cookie = self._cookie_header()
            if cookie:
                merged["Cookie"] = cookie
        return merged

    def _store_response_cookies(self, response) -> None:
        raw_values = []
        headers = getattr(response, "headers", {}) or {}
        getter = getattr(headers, "get", None)
        if getter:
            value = getter("set-cookie") or getter("Set-Cookie")
            if value:
                raw_values.append(value)
        get_list = getattr(headers, "get_list", None) or getattr(headers, "getlist", None)
        if get_list:
            try:
                raw_values.extend(get_list("set-cookie"))
            except Exception:
                pass
        for raw in raw_values:
            self._store_cookie_header(raw)

    def _store_cookie_header(self, raw: str) -> None:
        if not raw:
            return
        try:
            cookie = SimpleCookie()
            cookie.load(raw)
            for key, morsel in cookie.items():
                self._cookies()[key] = morsel.value
                self._save_state()
        except Exception:
            first = raw.split(";", 1)[0]
            if "=" in first:
                key, value = first.split("=", 1)
                self._cookies()[key.strip()] = value.strip()
                self._save_state()

    def _decode_cover_url(self, cover_url: str, base_url: str) -> str:
        if not cover_url:
            return ""
        absolute_url = urljoin(base_url, cover_url)
        if not self.source.coverDecodeJs:
            return absolute_url
        if not self.rhino:
            raise UnsupportedRuleError("coverDecodeJs requires Rhino")
        value = self.rhino.eval(
            str(self.source.coverDecodeJs),
            bindings={
                "result": absolute_url,
                "src": absolute_url,
                "url": absolute_url,
                "baseUrl": base_url,
            },
            scope_key=self.source_id,
            js_lib=self.source.jsLib or "",
        )
        self._save_state()
        return absolute_url if value is None else urljoin(base_url, str(value))

    def _apply_body_js(self, request, body: str, response: LegadoHttpResponse | None = None) -> str:
        if not getattr(request, "body_js", None):
            return body
        if not self.rhino:
            raise UnsupportedRuleError("URL bodyJs requires Rhino")
        bindings = {
            "result": body,
            "src": body,
            "body": body,
            "baseUrl": getattr(request, "url", ""),
        }
        if response is not None:
            bindings["response"] = {
                "body": response.body,
                "statusCode": response.statusCode,
                "code": response.code,
                "headers": response.headers,
                "url": response.url,
            }
        value = self.rhino.eval(str(request.body_js), bindings=bindings, scope_key=self.source_id, js_lib=self.source.jsLib or "")
        self._save_state()
        return "" if value is None else str(value)

    def _fetch(self, request) -> str:
        if request.webview or request.web_js:
            if not self.base_dir:
                raise RuntimeError("Legado WebView requires base_dir for persistent profile storage")
            body = PlaywrightWebView(
                self.base_dir,
                self.source_id,
                text_source=self.source.bookSourceType == 0,
            ).fetch(
                request.url,
                headers=request.headers or {},
                script=request.web_js,
                delay_ms=request.webview_delay_ms,
                bridge_handlers=self._webjs_handlers(request.url),
                cookie_state=self._cookies(),
            )
            body = self._apply_body_js(request, body)
            self._save_state()
            return body

        response = self._fetch_response(request)
        return self._apply_body_js(request, response.body, response)

    def _fetch_response(self, request) -> LegadoHttpResponse:
        headers = self._headers_with_cookies(request.headers or {})
        try:
            from curl_cffi import requests
            response = requests.request(
                request.method,
                request.url,
                headers=headers or None,
                data=request.body,
                impersonate="chrome110",
                timeout=30,
            )
        except ImportError:
            import requests
            response = requests.request(request.method, request.url, headers=headers or None, data=request.body, timeout=30)
        self._store_response_cookies(response)
        if request.charset:
            response.encoding = request.charset
        elif not getattr(response, "encoding", None):
            response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"
        self._save_state()
        return LegadoHttpResponse(
            body=response.text if request.method != "HEAD" else "",
            status_code=getattr(response, "status_code", 200),
            headers=dict(getattr(response, "headers", {}) or {}),
            url=getattr(response, "url", request.url),
        )
