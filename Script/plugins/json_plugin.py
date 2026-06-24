from bs4 import BeautifulSoup
from curl_cffi import requests
from plugins.base_plugin import BasePlugin, normalize_chapter_order
from urllib.parse import urljoin
import re

class JsonPlugin(BasePlugin):
    def __init__(self, config: dict):
        self.config = config
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

    @property
    def source_id(self) -> str:
        return self.config.get("id", "unknown")

    @property
    def source_name(self) -> str:
        return self.config.get("name", "Unknown Source")

    def _decode_response(self, response) -> str:
        content = response.content or b""
        header = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
        head = content[:4096].decode("ascii", errors="ignore")
        match = re.search(r"charset=[\"']?([\w-]+)", f"{header} {head}", re.I)
        preferred = (match.group(1).lower() if match else "")
        if preferred in {"gb2312", "gbk", "gb18030"}:
            preferred = "gb18030"
        candidates = [enc for enc in [preferred, "utf-8", "gb18030"] if enc]
        for encoding in dict.fromkeys(candidates):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode(candidates[0] if candidates else "utf-8", errors="replace")

    def _fetch(self, url: str):
        try:
            r = requests.get(url, headers=self.headers, impersonate="chrome110", timeout=20)
            return self._decode_response(r)
        except Exception as e:
            print(f"[{self.source_id}] Lỗi fetch {url}: {e}")
            return ""

    def _fetch_rendered(self, url: str):
        try:
            import shutil
            from playwright.sync_api import sync_playwright
        except Exception as e:
            print(f"[{self.source_id}] Playwright chưa sẵn sàng cho {url}: {e}")
            return ""

        executable = shutil.which("chromium") or shutil.which("chromium-browser")
        try:
            with sync_playwright() as p:
                kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}
                if executable:
                    kwargs["executable_path"] = executable
                browser = p.chromium.launch(**kwargs)
                try:
                    page = browser.new_page(user_agent=self.headers["User-Agent"])
                    if self.config.get("content_type") == "text":
                        page.route("**/*", lambda route: route.abort() if route.request.resource_type == "image" else route.continue_())
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    return page.content()
                finally:
                    browser.close()
        except Exception as e:
            print(f"[{self.source_id}] Lỗi render {url}: {e}")
            return ""

    def _resolve_toc_url(self, novel_url: str) -> str:
        sels = self.config.get("crawl_selectors", {})
        pattern = sels.get("toc_url_regex")
        template = sels.get("toc_url_template")
        if not pattern or not template:
            return novel_url
        match = re.search(pattern, novel_url)
        if not match:
            return novel_url
        groups = {f"group{i}": value for i, value in enumerate(match.groups(), 1)}
        return template.format(*match.groups(), **groups)


    def _meta_content(self, soup, *names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _pick_title(self, soup) -> str:
        title = self._meta_content(soup, "og:title", "twitter:title")
        if title:
            return self._clean_text(re.split(r"[_\-|]", title)[0])
        h1 = soup.find("h1")
        if h1:
            return self._clean_text(h1.get_text(" ", strip=True))
        if soup.title:
            return self._clean_text(re.split(r"[_\-|]", soup.title.get_text(" ", strip=True))[0])
        return ""

    def _pick_author(self, soup) -> str:
        for selector in [".author", ".writer", ".book-author", "#author"]:
            node = soup.select_one(selector)
            if node:
                text = self._clean_text(node.get_text(" ", strip=True))
                text = re.sub(r"^(作者|作家)[:：\s]*", "", text)
                if text:
                    return text
        page_text = self._clean_text(soup.get_text(" ", strip=True))
        match = re.search(r"作者[:：\s]*([^\s/|，。]+)", page_text)
        return match.group(1).strip() if match else ""

    def _pick_description(self, soup) -> str:
        desc = self._meta_content(soup, "og:description", "description", "twitter:description")
        if desc:
            return self._clean_text(desc)
        for selector in ["#intro", ".intro", ".book-intro", ".bookintro", ".description", ".desc", "#bookintro"]:
            node = soup.select_one(selector)
            if node:
                text = self._clean_text(node.get_text(" ", strip=True))
                if len(text) >= 20:
                    return text
        return ""

    def _pick_cover(self, soup, novel_url: str) -> str:
        cover = self._meta_content(soup, "og:image", "twitter:image")
        if cover:
            return urljoin(novel_url, cover)
        for selector in [".cover img", ".book-cover img", ".bookcover img", ".book-img img", ".img_in img", "#fmimg img", "img"]:
            img = soup.select_one(selector)
            if img:
                src = img.get("src") or img.get("data-src") or img.get("data-original")
                if src:
                    return urljoin(novel_url, src)
        return ""

    def get_metadata(self, novel_url: str) -> dict:
        html = self._fetch(novel_url)
        if not html:
            return {}
        soup = BeautifulSoup(html, 'html.parser')
        return {
            "title": self._pick_title(soup),
            "author": self._pick_author(soup),
            "description": self._pick_description(soup),
            "cover_url": self._pick_cover(soup, novel_url),
            "source_url": novel_url,
            "source_id": self.source_id,
            "source_name": self.source_name,
        }

    def get_toc(self, novel_url: str) -> list:
        toc_url = self._resolve_toc_url(novel_url)
        html = self._fetch(toc_url)
        if not html: return []
        
        soup = BeautifulSoup(html, 'html.parser')
        sels = self.config.get("crawl_selectors", {})
        list_selector = sels.get("chapter_list", "a")
        
        chapters = []
        for a in soup.select(list_selector):
            href = a.get("href")
            if not href: continue
            title = a.get_text(strip=True)
            if not title or title in {"首页", "上一页", "下一页", "尾页", "目录"} or "直达" in title:
                continue
            if not any(marker in title for marker in ("第", "章", "卷", "集", "篇", "回")):
                continue
            url = urljoin(toc_url, href)
            chapters.append({"title": title, "url": url})
            
        return normalize_chapter_order(chapters)

    def _extract_content_text(self, soup, content_selector: str) -> str:
        content_div = soup.select_one(content_selector)
        if not content_div and content_selector == "body":
            content_div = soup
        if not content_div:
            return ""

        content_div = BeautifulSoup(str(content_div), 'html.parser')
        for unwanted in content_div.find_all(['title', 'meta', 'link', 'h1', 'script', 'style', 'a']):
            unwanted.decompose()
        return content_div.get_text(separator='\n\n', strip=True)

    def _find_next_content_url(self, soup, page_url: str, sels: dict) -> str:
        selector = sels.get("next_content_selector") or sels.get("nextContentUrl")
        if not selector:
            return ""

        target_text = sels.get("next_content_text")
        if selector.startswith("text."):
            parts = selector.split("@", 1)
            target_text = parts[0].replace("text.", "", 1)
            selector = "a"

        candidates = soup.select(selector)
        for node in candidates:
            if target_text and target_text not in node.get_text(" ", strip=True):
                continue
            href = node.get("href")
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue
            return urljoin(page_url, href)
        return ""

    def get_chapter(self, chapter_url: str) -> str:
        sels = self.config.get("crawl_selectors", {})
        content_selector = sels.get("chapter_content", "body")
        max_pages = int(sels.get("max_content_pages", 1) or 1)

        parts = []
        seen = set()
        page_url = chapter_url
        for _ in range(max_pages):
            if not page_url or page_url in seen:
                break
            seen.add(page_url)

            html = self._fetch_rendered(page_url) if self.config.get("requires_js") else self._fetch(page_url)
            if not html:
                break

            soup = BeautifulSoup(html, 'html.parser')
            text = self._extract_content_text(soup, content_selector)
            if text:
                parts.append(text)

            page_url = self._find_next_content_url(soup, page_url, sels)

        return "\n\n".join(part for part in parts if part)
