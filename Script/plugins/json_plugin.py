from bs4 import BeautifulSoup
from curl_cffi import requests
from plugins.base_plugin import BasePlugin
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

    def _fetch(self, url: str):
        try:
            r = requests.get(url, headers=self.headers, impersonate="chrome110", timeout=15)
            # detect encoding
            if "charset=gbk" in r.text.lower() or "charset=gb2312" in r.text.lower():
                r.encoding = 'gbk'
            return r.text
        except Exception as e:
            print(f"[{self.source_id}] Lỗi fetch {url}: {e}")
            return ""

    def get_toc(self, novel_url: str) -> list:
        html = self._fetch(novel_url)
        if not html: return []
        
        soup = BeautifulSoup(html, 'html.parser')
        sels = self.config.get("crawl_selectors", {})
        list_selector = sels.get("chapter_list", "a")
        
        chapters = []
        for a in soup.select(list_selector):
            href = a.get("href")
            if not href: continue
            title = a.get_text(strip=True)
            url = urljoin(novel_url, href)
            chapters.append({"title": title, "url": url})
            
        return chapters

    def get_chapter(self, chapter_url: str) -> str:
        html = self._fetch(chapter_url)
        if not html: return ""
        
        soup = BeautifulSoup(html, 'html.parser')
        sels = self.config.get("crawl_selectors", {})
        content_selector = sels.get("chapter_content", "body")
        
        content_div = soup.select_one(content_selector)
        if not content_div: return ""
        
        # Remove unwanted tags
        for unwanted in content_div.find_all(['h1', 'div', 'script', 'style', 'a']):
            unwanted.decompose()
            
        return content_div.get_text(separator='\n\n', strip=True)
