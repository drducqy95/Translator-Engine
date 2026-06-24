from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Dict, Optional


_JS_MARKERS = (
    "@js:",
    "<js>",
    '"js"',
    "jsLib",
    "bodyJs",
    "formatJs",
    "preUpdateJs",
    "coverDecodeJs",
    "loginCheckJs",
    "imageDecode",
    "callBackJs",
    "java.",
    "source.",
    "book.",
    "chapter.",
    "cookie.",
    "cache.",
)
_WEBVIEW_MARKERS = (
    '"webView"',
    "'webView'",
    "webView",
    "webJs",
    "sourceRegex",
    "overrideUrlRegex",
    "startBrowserAwait",
    "loginUi",
)
_JSONPATH_RE = re.compile(r"(^|[^\w])\$[.[]")
_XPATH_RE = re.compile(r"(^|[@\s])(/|//|@XPath:)")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dataclass_from_dict(cls, value: Any):
    data = _as_dict(value)
    names = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class SearchRule:
    checkKeyWord: Optional[str] = None
    bookList: Optional[str] = None
    name: Optional[str] = None
    author: Optional[str] = None
    intro: Optional[str] = None
    kind: Optional[str] = None
    lastChapter: Optional[str] = None
    updateTime: Optional[str] = None
    bookUrl: Optional[str] = None
    coverUrl: Optional[str] = None
    wordCount: Optional[str] = None


@dataclass
class BookInfoRule:
    init: Optional[str] = None
    name: Optional[str] = None
    author: Optional[str] = None
    intro: Optional[str] = None
    kind: Optional[str] = None
    lastChapter: Optional[str] = None
    updateTime: Optional[str] = None
    coverUrl: Optional[str] = None
    tocUrl: Optional[str] = None
    wordCount: Optional[str] = None
    canReName: Optional[str] = None
    downloadUrls: Optional[str] = None


@dataclass
class TocRule:
    preUpdateJs: Optional[str] = None
    chapterList: Optional[str] = None
    chapterName: Optional[str] = None
    chapterUrl: Optional[str] = None
    formatJs: Optional[str] = None
    isVolume: Optional[str] = None
    isVip: Optional[str] = None
    isPay: Optional[str] = None
    updateTime: Optional[str] = None
    nextTocUrl: Optional[str] = None


@dataclass
class ContentRule:
    content: Optional[str] = None
    subContent: Optional[str] = None
    title: Optional[str] = None
    nextContentUrl: Optional[str] = None
    webJs: Optional[str] = None
    sourceRegex: Optional[str] = None
    replaceRegex: Optional[str] = None
    imageStyle: Optional[str] = None
    imageDecode: Optional[str] = None
    payAction: Optional[str] = None
    callBackJs: Optional[str] = None


@dataclass
class BookSource:
    bookSourceUrl: str = ""
    bookSourceName: str = ""
    bookSourceGroup: Optional[str] = None
    bookSourceType: int = 0
    bookUrlPattern: Optional[str] = None
    customOrder: int = 0
    enabled: bool = True
    enabledExplore: bool = True
    jsLib: Optional[str] = None
    enabledCookieJar: Optional[bool] = True
    concurrentRate: Optional[str] = None
    header: Optional[str] = None
    loginUrl: Optional[str] = None
    loginUi: Optional[str] = None
    loginCheckJs: Optional[str] = None
    coverDecodeJs: Optional[str] = None
    bookSourceComment: Optional[str] = None
    variableComment: Optional[str] = None
    lastUpdateTime: int = 0
    respondTime: int = 180000
    weight: int = 0
    exploreUrl: Optional[str] = None
    exploreScreen: Optional[str] = None
    ruleExplore: Dict[str, Any] = field(default_factory=dict)
    searchUrl: Optional[str] = None
    ruleSearch: SearchRule = field(default_factory=SearchRule)
    ruleBookInfo: BookInfoRule = field(default_factory=BookInfoRule)
    ruleToc: TocRule = field(default_factory=TocRule)
    ruleContent: ContentRule = field(default_factory=ContentRule)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookSource":
        source = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and not k.startswith("rule")})
        source.ruleExplore = _as_dict(data.get("ruleExplore"))
        source.ruleSearch = _dataclass_from_dict(SearchRule, data.get("ruleSearch"))
        source.ruleBookInfo = _dataclass_from_dict(BookInfoRule, data.get("ruleBookInfo"))
        source.ruleToc = _dataclass_from_dict(TocRule, data.get("ruleToc"))
        source.ruleContent = _dataclass_from_dict(ContentRule, data.get("ruleContent"))
        source.raw = dict(data)
        return source

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.raw)
        if not data:
            data = self.__dict__.copy()
            data.pop("raw", None)
        return data

    @property
    def key(self) -> str:
        return self.bookSourceUrl or self.bookSourceName

    @property
    def name(self) -> str:
        return self.bookSourceName or self.bookSourceUrl or "Legado Source"


def source_plugin_id(source: BookSource | Dict[str, Any]) -> str:
    key = source.key if isinstance(source, BookSource) else str(source.get("bookSourceUrl") or source.get("bookSourceName") or "")
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"legado:{digest}"


def _source_text(source: BookSource | Dict[str, Any]) -> str:
    data = source.to_dict() if isinstance(source, BookSource) else source
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def classify_source(source: BookSource | Dict[str, Any]) -> Dict[str, Any]:
    text = _source_text(source)
    needs_js = any(marker in text for marker in _JS_MARKERS)
    needs_webview = any(marker in text for marker in _WEBVIEW_MARKERS)
    uses_jsonpath = bool(_JSONPATH_RE.search(text) or "@Json:" in text)
    uses_xpath = bool(_XPATH_RE.search(text))
    support = "native"
    reasons = []
    if needs_webview:
        support = "webview"
        reasons.append("webview")
    if needs_js:
        support = "rhino" if support == "native" else "partial"
        reasons.append("rhino")
    if "startBrowserAwait" in text or "loginUi" in text:
        if support == "native":
            support = "webview"
        elif support == "rhino":
            support = "partial"
        reasons.append("manual_login")
    return {
        "needs_js": needs_js,
        "needs_webview": needs_webview,
        "uses_jsonpath": uses_jsonpath,
        "uses_xpath": uses_xpath,
        "support_level": support,
        "reasons": sorted(set(reasons)),
    }
