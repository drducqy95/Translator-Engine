from plugins.base_plugin import BasePlugin
from bs4 import BeautifulSoup
from curl_cffi import requests
from urllib.parse import urlparse
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
            'Referer': 'https://69shuba.cx/',
        }

    def _fetch(self, url: str):
        # Fix URL domain
        parsed = urlparse(url)
        url = url.replace(parsed.netloc, "www.69shuba.cx")
        
        r = requests.get(url, headers=self.headers, impersonate="chrome110", timeout=15)
        r.encoding = 'gbk'
        return r.text

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
                # Fix domain again
                parsed = urlparse(href)
                safe_link = href.replace(parsed.netloc, "www.69shuba.cx")
                chapters.append({"title": title, "url": safe_link})
                
        return chapters

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
