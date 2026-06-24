from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Callable, Iterable, List
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from .models import BookSource, classify_source, source_plugin_id

FetchFn = Callable[[str], str]
_IMPORT_QUERY_KEYS = ("src", "url", "source", "sourceUrl", "bookSourceUrl", "file")
_DIRECT_SOURCE_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_SCHEME_RE = re.compile(r"(?:yuedu|legado)://[^\s'\"<>]+", re.IGNORECASE)
_IMPORTONLINE_RE = re.compile(r"(?:^|[?&])(?:src|url|source|sourceUrl|bookSourceUrl|file)=([^&\s'\"<>]+)", re.IGNORECASE)
_JSON_KEY_RE = re.compile(r"[\"'](?:bookSourceUrl|bookSources|sources)[\"']")


def _clean_text(text: str) -> str:
    return html.unescape((text or "").lstrip("\ufeff").strip())


def _recursive_unquote(value: str, limit: int = 4) -> str:
    current = html.unescape((value or "").strip())
    for _ in range(limit):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _sources_from_data(data) -> List[BookSource]:
    if isinstance(data, dict):
        if isinstance(data.get("bookSources"), list):
            data = data["bookSources"]
        elif isinstance(data.get("sources"), list):
            data = data["sources"]
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    return [BookSource.from_dict(item) for item in data if isinstance(item, dict) and item.get("bookSourceUrl")]


def _decode_query_source(query: str) -> str:
    parsed = parse_qs(query, keep_blank_values=True)
    for key in _IMPORT_QUERY_KEYS:
        values = parsed.get(key)
        if values and values[0]:
            return _recursive_unquote(values[0])
    match = _IMPORTONLINE_RE.search("?" + query.lstrip("?"))
    return _recursive_unquote(match.group(1)) if match else ""


def decode_importonline_link(link: str) -> str:
    if not link:
        return ""
    link = html.unescape(link.strip())
    parsed = urlparse(link)
    if parsed.scheme.lower() in {"yuedu", "legado"}:
        decoded = _decode_query_source(parsed.query)
        if decoded:
            return decoded
    if "importonline" in link.lower() or "src=" in link.lower():
        decoded = _decode_query_source(parsed.query or link)
        if decoded:
            return decoded
    return _recursive_unquote(link)


def extract_import_links(text: str) -> List[str]:
    text = _clean_text(text)
    links: list[str] = []
    seen: set[str] = set()

    def add(link: str) -> None:
        link = html.unescape(link.rstrip(".,);]"))
        if link and link not in seen:
            seen.add(link)
            links.append(link)

    for match in _SCHEME_RE.finditer(text):
        add(match.group(0))
    for match in _DIRECT_SOURCE_RE.finditer(text):
        url = match.group(0)
        lower = url.lower()
        if any(token in lower for token in ("booksource", "source", "legado", "yuedu", ".json", ".txt", "importonline")):
            add(url)
    if not links:
        for match in _IMPORTONLINE_RE.finditer(text):
            add(_recursive_unquote(match.group(1)))
    return links


def _json_candidates(text: str) -> Iterable[str]:
    decoder = json.JSONDecoder()
    starts = sorted({m.start() for m in re.finditer(r"[\[{]", text)})
    for start in starts:
        window = text[start : start + 20000]
        if not _JSON_KEY_RE.search(window):
            continue
        try:
            _, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        yield text[start : start + end]


def parse_sources_text(text: str) -> List[BookSource]:
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        return []

    try:
        sources = _sources_from_data(json.loads(raw))
    except json.JSONDecodeError:
        sources = []
    if sources:
        return sources

    variants = []
    for candidate in (html.unescape(raw), _recursive_unquote(raw)):
        if candidate and candidate not in variants:
            variants.append(candidate)

    for variant in variants:
        if variant != raw:
            try:
                sources = _sources_from_data(json.loads(variant))
            except json.JSONDecodeError:
                sources = []
            if sources:
                return sources
        for candidate in _json_candidates(variant):
            try:
                sources = _sources_from_data(json.loads(candidate))
            except json.JSONDecodeError:
                continue
            if sources:
                return sources
    return []


def _default_fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 LegadoImporter/1.0"})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _is_url(value: str) -> bool:
    return urlparse(value).scheme.lower() in {"http", "https"}


def _maybe_existing_path(value: str | Path) -> Path | None:
    if isinstance(value, Path):
        return value if value.exists() else None
    raw = str(value)
    if "\n" in raw or len(raw) > 500 or raw.lstrip().startswith(("[", "{", "<")):
        return None
    try:
        path = Path(raw)
        return path if path.exists() else None
    except OSError:
        return None


def load_sources_location(location: str | Path, fetcher: FetchFn | None = None) -> List[BookSource]:
    path = _maybe_existing_path(location)
    if path is not None:
        return parse_sources_text(path.read_text(encoding="utf-8"))

    value = (str(location) or "").lstrip("\ufeff").strip()
    sources = parse_sources_text(value)
    if sources:
        return sources

    value = _clean_text(value)
    is_single_link = not any(ch in value for ch in "<>\n\r")
    if is_single_link:
        decoded = decode_importonline_link(value)
        if decoded != value:
            if _is_url(decoded):
                return load_sources_location(decoded, fetcher=fetcher)
            sources = parse_sources_text(decoded)
            if sources:
                return sources

    if _is_url(value):
        body = (fetcher or _default_fetch)(value)
        sources = parse_sources_text(body)
        if sources:
            return sources
        return _load_sources_from_links(body, fetcher=fetcher)

    return _load_sources_from_links(value, fetcher=fetcher)


def _load_sources_from_links(text: str, fetcher: FetchFn | None = None) -> List[BookSource]:
    for link in extract_import_links(text):
        decoded = decode_importonline_link(link)
        if _is_url(decoded):
            body = (fetcher or _default_fetch)(decoded)
            sources = parse_sources_text(body)
            if sources:
                return sources
            nested = _load_sources_from_links(body, fetcher=fetcher)
            if nested:
                return nested
        else:
            sources = parse_sources_text(decoded)
            if sources:
                return sources
    return []


def load_sources_file(path: str | Path) -> List[BookSource]:
    return parse_sources_text(Path(path).read_text(encoding="utf-8"))


def write_sources_cache(sources: Iterable[BookSource], path: str | Path) -> List[dict]:
    records = []
    seen: set[str] = set()
    for source in sources:
        key = source.bookSourceUrl or source.bookSourceName
        if key in seen:
            continue
        seen.add(key)
        data = source.to_dict()
        data["_plugin_id"] = source_plugin_id(source)
        data["_classification"] = classify_source(source)
        records.append(data)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sources": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def import_sources(location: str | Path, path: str | Path, fetcher: FetchFn | None = None) -> List[dict]:
    return write_sources_cache(load_sources_location(location, fetcher=fetcher), path)
