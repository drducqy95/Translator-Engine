from plugins.base_plugin import BasePlugin, normalize_chapter_order
from bs4 import BeautifulSoup
from curl_cffi import requests
from urllib.parse import urljoin, urlparse, urlunparse
import time
import random

class Plugin69Shuba(BasePlugin):
    @property
    def source_id(self) -> str:
        return "69shuba"

    @property
    def source_name(self) -> str:
        return "69shuba (69 Thư Ba)"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:101.0) Gecko/20100101 Firefox/101.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Referer': 'https://www.69shuba.com/',
        }

    def _normalize_url(self, url: str, base: str = "https://www.69shuba.com/") -> str:
        url = urljoin(base, url)
        parsed = urlparse(url)
        return urlunparse(parsed._replace(netloc="www.69shuba.com"))

    def _fetch(self, url: str):
        url = self._normalize_url(url)

        r = requests.get(url, headers=self.headers, impersonate="chrome110", timeout=15)
        r.encoding = 'gbk'
        return r.text


    def _clean_text(self, text: str) -> str:
        import re
        return re.sub(r"\s+", " ", text or "").strip()

    def _meta_content(self, soup, *names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    def get_metadata(self, novel_url: str) -> dict:
        import re
        html = self._fetch(novel_url)
        if not html or "Just a moment" in html or "Cloudflare" in html:
            return {}

        soup = BeautifulSoup(html, 'html.parser')
        title = self._meta_content(soup, "og:title", "twitter:title")
        if not title:
            h1 = soup.find('h1')
            title = h1.get_text(' ', strip=True) if h1 else ""
        if not title and soup.title:
            title = soup.title.get_text(' ', strip=True)
        title = self._clean_text(re.split(r"[_\-|]", title)[0])

        page_text = self._clean_text(soup.get_text(' ', strip=True))
        author = ""
        for selector in ['.author', '.writer', '.book-author', '#author']:
            node = soup.select_one(selector)
            if node:
                author = self._clean_text(re.sub(r"^(作者|作家)[:：\s]*", "", node.get_text(' ', strip=True)))
                if author:
                    break
        if not author:
            match = re.search(r"作者[:：\s]*([^\s/|，。]+)", page_text)
            author = match.group(1).strip() if match else ""

        description = self._meta_content(soup, "og:description", "description", "twitter:description")
        if not description:
            for selector in ['#intro', '.intro', '.book-intro', '.bookintro', '.description', '.desc']:
                node = soup.select_one(selector)
                if node:
                    description = self._clean_text(node.get_text(' ', strip=True))
                    if len(description) >= 20:
                        break
        description = self._clean_text(description)

        cover_url = self._meta_content(soup, "og:image", "twitter:image")
        if not cover_url:
            for selector in ['.cover img', '.book-cover img', '.bookcover img', '.book-img img', '#fmimg img', 'img']:
                img = soup.select_one(selector)
                if img:
                    cover_url = img.get('src') or img.get('data-src') or img.get('data-original') or ""
                    if cover_url:
                        break
        if cover_url:
            cover_url = self._normalize_url(cover_url, novel_url)

        return {
            "title": title,
            "author": author,
            "description": description,
            "cover_url": cover_url,
            "source_url": self._normalize_url(novel_url),
            "source_id": self.source_id,
            "source_name": self.source_name,
        }

    def get_toc(self, novel_url: str) -> list:
        # If url is .htm, change to /
        if novel_url.endswith('.htm'):
            novel_url = novel_url[:-4] + '/'
            
        html = self._fetch(novel_url)
        if "Just a moment" in html or "Cloudflare" in html:
            print("[69shuba] Bị Cloudflare chặn!")
            return []
            
        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select('div#catalog li a') or soup.select('.catalog li a')
        
        chapters = []
        for a in items:
            href = a.get('href')
            if href and '/txt/' in href:
                title = a.get_text(strip=True)
                safe_link = self._normalize_url(href, novel_url)
                chapters.append({"title": title, "url": safe_link})
                
        return normalize_chapter_order(chapters)

    def get_chapter(self, chapter_url: str) -> str:
        html = self._fetch(chapter_url)
        if "Just a moment" in html:
            return ""
            
        soup = BeautifulSoup(html, 'html.parser')
        content_div = soup.find('div', class_='txtnav')
        
        if content_div:
            for unwanted in content_div.find_all(['h1', 'div']):
                unwanted.decompose()
            return content_div.get_text(separator='\n\n', strip=True)
        return ""
