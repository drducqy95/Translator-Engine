from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote, urljoin

from .rule_analyzer import split_text


@dataclass
class UrlRequest:
    url: str
    method: str = "GET"
    headers: Dict[str, str] | None = None
    body: Optional[str] = None
    charset: Optional[str] = None
    webview: bool = False
    web_js: Optional[str] = None
    body_js: Optional[str] = None
    option_js: Optional[str] = None
    retry: int = 0
    webview_delay_ms: int = 900


class AnalyzeUrl:
    def __init__(self, source, base_url: str = "", rhino=None, scope_key: str = "default", js_lib: str = ""):
        self.source = source
        self.base_url = base_url or getattr(source, "bookSourceUrl", "")
        self.rhino = rhino
        self.scope_key = scope_key
        self.js_lib = js_lib or ""

    def build(self, url_rule: str, **values: Any) -> UrlRequest:
        if not url_rule:
            return UrlRequest("")
        if url_rule.strip().startswith("@js:"):
            if not self.rhino:
                raise RuntimeError("AnalyzeUrl requires Rhino for @js URL rules")
            url_rule = str(self.rhino.eval(url_rule.strip()[4:], bindings={"key": values.get("keyword", values.get("key", "")), "page": values.get("page", 1), "baseUrl": self.base_url}, scope_key=self.scope_key, js_lib=self.js_lib) or "")
        url_rule = self._replace_templates(url_rule, values)
        raw_url, option = self._split_option(url_rule)
        option_js = option.get("js")
        if option_js:
            if not self.rhino:
                raise RuntimeError("AnalyzeUrl requires Rhino for URL option js")
            raw_url = str(self.rhino.eval(
                str(option_js),
                bindings={
                    "url": raw_url.strip(),
                    "result": raw_url.strip(),
                    "baseUrl": self.base_url,
                    "key": values.get("keyword", values.get("key", "")),
                    "page": values.get("page", 1),
                },
                scope_key=self.scope_key,
                js_lib=self.js_lib,
            ) or raw_url)
        headers = self._source_headers()
        headers.update({str(k): str(v) for k, v in (option.get("headers") or {}).items()})
        method = str(option.get("method") or "GET").upper()
        body = option.get("body")
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        return UrlRequest(
            url=urljoin(self.base_url, raw_url.strip()),
            method=method,
            headers=headers,
            body=str(body) if body is not None else None,
            charset=option.get("charset"),
            webview=option.get("webView") not in (None, "", False, "false"),
            web_js=option.get("webJs"),
            body_js=option.get("bodyJs"),
            option_js=option_js,
            retry=int(option.get("retry") or 0),
            webview_delay_ms=int(option.get("webViewDelayTime") or 900),
        )

    def _replace_templates(self, text: str, values: Dict[str, Any]) -> str:
        def repl(match):
            expr = match.group(1).strip()
            if expr in values:
                return str(values[expr])
            if expr == "key" and "keyword" in values:
                return quote(str(values["keyword"]))
            if expr == "page" and "page" in values:
                return str(values["page"])
            return match.group(0)
        text = text.replace("{{key}}", quote(str(values.get("keyword", values.get("key", "")))))
        text = text.replace("{{page}}", str(values.get("page", 1)))
        return re.sub(r"\{\{([^{}]+)\}\}", repl, text)

    def _split_option(self, url_rule: str):
        pieces = split_text(url_rule, [","], keep_empty=True)
        if len(pieces) < 2:
            return url_rule, {}
        maybe_json = ",".join(pieces[1:]).strip()
        if not maybe_json.startswith("{"):
            return url_rule, {}
        try:
            return pieces[0], json.loads(maybe_json)
        except Exception:
            return url_rule, {}

    def _source_headers(self) -> Dict[str, str]:
        header = getattr(self.source, "header", None)
        if not header:
            return {}
        try:
            data = json.loads(header)
        except Exception:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
