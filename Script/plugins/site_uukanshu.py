import json
import os
import re
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from plugins.base_plugin import BasePlugin, normalize_chapter_order


class CloudflareBlocked(RuntimeError):
    pass


class PluginUUKanshu(BasePlugin):
    """UUKanshu source with explicit Cloudflare/cookie/FlareSolverr handling."""

    base_url = "https://uukanshu.cc/"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": self.base_url,
        }
        cookie = self._configured_cookie()
        if cookie:
            self.headers["Cookie"] = cookie

    @property
    def source_id(self) -> str:
        return "uukanshu"

    @property
    def source_name(self) -> str:
        return "UUKanshu"

    def _configured_cookie(self) -> str:
        env_cookie = os.getenv("UUKANSHU_COOKIE") or os.getenv("UUKANSHU_CC_COOKIE")
        if env_cookie:
            return env_cookie.strip()
        path = Path(__file__).resolve().parents[2] / "Dashboard" / "data" / "legado" / "cookies.json"
        if not path.exists():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        for key in (self.source_id, self.base_url.rstrip("/"), self.base_url, "https://www.uukanshu.cc"):
            value = data.get(key) if isinstance(data, dict) else None
            if value:
                return self._cookie_to_header(value)
        return ""

    def _cookie_to_header(self, value) -> str:
        if isinstance(value, dict):
            return "; ".join(f"{k}={v}" for k, v in value.items() if v not in (None, ""))
        cookie = SimpleCookie()
        try:
            cookie.load(str(value))
            if cookie:
                return "; ".join(f"{k}={m.value}" for k, m in cookie.items())
        except Exception:
            pass
        return str(value).strip()

    def _normalize_url(self, url: str, base: str | None = None) -> str:
        absolute = urljoin(base or self.base_url, url or "")
        parsed = urlparse(absolute)
        host = "uukanshu.cc" if parsed.netloc in {"www.uukanshu.cc", "m.uukanshu.cc"} else parsed.netloc
        return urlunparse(parsed._replace(scheme="https", netloc=host))

    def _is_cloudflare_challenge(self, html: str) -> bool:
        text = html or ""
        return any(marker in text for marker in (
            "cf-mitigated",
            "challenge-platform",
            "Just a moment",
            "正在进行安全验证",
            "Enable JavaScript and cookies",
        ))

    def _fetch(self, url: str) -> str:
        url = self._normalize_url(url)
        flaresolverr = os.getenv("FLARESOLVERR_URL", "").strip().rstrip("/")
        if flaresolverr:
            html = self._fetch_with_flaresolverr(flaresolverr, url)
        else:
            response = requests.get(url, headers=self.headers, impersonate="chrome120", timeout=30)
            html = self._decode_response(response)
        if self._is_cloudflare_challenge(html):
            raise CloudflareBlocked(
                "uukanshu.cc is protected by Cloudflare; provide UUKANSHU_COOKIE or FLARESOLVERR_URL"
            )
        return html

    def _fetch_with_flaresolverr(self, endpoint: str, url: str) -> str:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 90000,
            "headers": self.headers,
        }
        response = requests.post(f"{endpoint}/v1", json=payload, timeout=100)
        data = response.json()
        if data.get("status") != "ok":
            raise CloudflareBlocked(data.get("message") or "FlareSolverr failed")
        solution = data.get("solution") or {}
        return solution.get("response") or ""

    def _decode_response(self, response) -> str:
        content = response.content or b""
        header = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
        head = content[:4096].decode("ascii", errors="ignore")
        match = re.search(r"charset=[\"']?([\w-]+)", f"{header} {head}", re.I)
        preferred = (match.group(1).lower() if match else "utf-8")
        if preferred in {"gb2312", "gbk", "gb18030"}:
            preferred = "gb18030"
        for encoding in dict.fromkeys([preferred, "utf-8", "gb18030"]):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def search(self, keyword: str) -> list:
        html = self._fetch(f"/search/{quote(keyword)}")
        soup = BeautifulSoup(html, "html.parser")
        return self._parse_book_cards(soup)

    def _parse_book_cards(self, soup: BeautifulSoup) -> list:
        cards = soup.select(".book-list li, .bookbox, .library li, .novel-item, li")
        out = []
        seen = set()
        for card in cards:
            link = card.select_one("h3 a, .bookname a, .name a, a[href*='/book/']")
            if not link:
                continue
            title = self._clean(link.get_text(" ", strip=True))
            href = link.get("href")
            if not title or not href:
                continue
            book_url = self._normalize_url(href)
            if book_url in seen:
                continue
            seen.add(book_url)
            author = ""
            for selector in (".author", ".writer", ".book-author", "p"):
                node = card.select_one(selector)
                if node:
                    author = re.sub(r"^(作者|作家)[:：\s]*", "", self._clean(node.get_text(" ", strip=True)))
                    break
            out.append({"title": title, "author": author, "url": book_url, "source_id": self.source_id, "source_name": self.source_name})
        return out

    def get_metadata(self, novel_url: str) -> dict:
        novel_url = self._normalize_url(novel_url)
        soup = BeautifulSoup(self._fetch(novel_url), "html.parser")
        title = self._meta(soup, "og:title", "twitter:title")
        if not title:
            node = soup.select_one("h1, .book-info h2, .info h1, .booktitle")
            title = node.get_text(" ", strip=True) if node else ""
        author = ""
        for selector in (".author", ".writer", ".book-author", "#author", ".info p"):
            node = soup.select_one(selector)
            if node:
                text = self._clean(node.get_text(" ", strip=True))
                match = re.search(r"作者[:：\s]*([^/|，。]+)", text)
                author = match.group(1) if match else re.sub(r"^(作者|作家)[:：\s]*", "", text)
                if author:
                    break
        desc = self._meta(soup, "og:description", "description", "twitter:description")
        if not desc:
            node = soup.select_one("#intro, .intro, .book-intro, .desc, .description")
            desc = node.get_text(" ", strip=True) if node else ""
        cover = self._meta(soup, "og:image", "twitter:image")
        if not cover:
            img = soup.select_one(".cover img, .book-cover img, .book-img img, img")
            cover = (img.get("src") or img.get("data-src") or img.get("data-original") or "") if img else ""
        return {
            "title": self._clean(re.split(r"[_\-|]", title)[0]),
            "author": self._clean(author),
            "description": self._clean(desc),
            "cover_url": self._normalize_url(cover, novel_url) if cover else "",
            "source_url": novel_url,
            "source_id": self.source_id,
            "source_name": self.source_name,
        }

    def _meta(self, soup: BeautifulSoup, *names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    def get_toc(self, novel_url: str) -> list:
        novel_url = self._normalize_url(novel_url)
        soup = BeautifulSoup(self._fetch(novel_url), "html.parser")
        selectors = [
            "#chapterList li a", "#chapterlist li a", "#list li a", "#list dd a",
            ".chapter-list li a", ".chapterlist li a", ".book-chapter-list a", "a[href*='/book/']",
        ]
        chapters = []
        seen = set()
        for selector in selectors:
            for link in soup.select(selector):
                href = link.get("href")
                title = self._clean(link.get_text(" ", strip=True))
                if not href or not title or title in {"首页", "上一页", "下一页", "尾页", "目录"}:
                    continue
                if not any(marker in title for marker in ("第", "章", "卷", "集", "篇", "回")):
                    continue
                url = self._normalize_url(href, novel_url)
                if url in seen or url == novel_url:
                    continue
                seen.add(url)
                chapters.append({"title": title, "url": url})
            if chapters:
                break
        return normalize_chapter_order(chapters)

    def get_chapter(self, chapter_url: str) -> str:
        chapter_url = self._normalize_url(chapter_url)
        soup = BeautifulSoup(self._fetch(chapter_url), "html.parser")
        for selector in ("#contentbox", "#content", ".content", ".chapter-content", "article"):
            node = soup.select_one(selector)
            if not node:
                continue
            content = BeautifulSoup(str(node), "html.parser")
            for unwanted in content.find_all(["script", "style", "a", "ins", "iframe"]):
                unwanted.decompose()
            text = content.get_text("\n\n", strip=True)
            if len(text.strip()) >= 20:
                return text
        return ""
