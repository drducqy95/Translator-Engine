import json
import mimetypes
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from pipeline_manager import PipelineManager
from plugins.base_plugin import normalize_chapter_order

def _launch_chromium(playwright):
    candidates = [
        os.getenv("CHROMIUM_EXECUTABLE"),
        shutil.which("chromium"),
        shutil.which("google-chrome"),
        getattr(playwright.chromium, "executable_path", None),
        shutil.which("chromium-browser"),
        None,
    ]
    last_error = None
    for executable in candidates:
        if executable == "":
            continue
        kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}
        if executable:
            kwargs["executable_path"] = executable
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:
            last_error = exc
    raise last_error


def _is_cloudflare_html(html: str) -> bool:
    text = html or ""
    markers = (
        "Just a moment",
        "cf-mitigated",
        "challenge-platform",
        "Enable JavaScript and cookies",
        "正在进行安全验证",
        "Cloudflare",
        "Attention Required!",
    )
    return any(marker in text for marker in markers)



class SourceManager:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.source_full_dir = self.base_dir / "Source_Full"
        self.source_split_dir = self.base_dir / "Source_Split"
        self.output_dir = self.base_dir / "Output"
        
        # Đảm bảo các thư mục gốc luôn tồn tại
        self.source_full_dir.mkdir(parents=True, exist_ok=True)
        self.source_split_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.crawl_jobs = {}


    # ==========================================
    # MẢNG 1: TÁCH FILE FULL & KHỞI TẠO PIPELINE
    # ==========================================
    def split_and_init_novel(self, novel_id: str, full_txt_filename: str):
        """Đọc file .txt gốc, tách thành các file Markdown nhỏ theo chương, và khởi tạo Pipeline."""
        print(f"\n[SourceManager] Bắt đầu tách truyện: {novel_id} từ {full_txt_filename}")
        full_path = self.source_full_dir / full_txt_filename
        if not full_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file: {full_path}")
            
        novel_split_dir = self.source_split_dir / novel_id
        novel_split_dir.mkdir(parents=True, exist_ok=True)
        
        import chapter_splitter
        print(f'📖 Đang đọc bằng thư viện chia chương chuẩn: {full_path.name}')
        lines = chapter_splitter.extract_lines(full_path)
        
        chapters = []
        for idx, line in enumerate(lines):
            found = chapter_splitter.detect_chapter_heading(line)
            if found:
                chapters.append((found[0], found[1], found[2], idx))
                
        if not chapters:
            print(f'⚠️ Không tìm thấy Header chương nào trong file: {full_path.name}')
            return
            
        # Re-splitting must remove stale files first; otherwise renamed titles leave
        # duplicate Chapter N files and corrupt TOC/order. Keep metadata/cover files intact.
        for old_chapter in novel_split_dir.glob("Chapter *.md"):
            old_chapter.unlink()
        intro_file = novel_split_dir / "Intro.md"
        if intro_file.exists():
            intro_file.unlink()

        # Tạo Intro.md nếu có content trước chương 1
        intro_body = ''.join(lines[:chapters[0][3]]).strip()
        if intro_body:
            with open(novel_split_dir / "Intro.md", 'w', encoding='utf-8') as f:
                f.write(intro_body)
                
        for pos, (chapter_number, title, original_heading, start_idx) in enumerate(chapters):
            end_idx = chapters[pos + 1][3] if pos + 1 < len(chapters) else len(lines)
            body = ''.join(lines[start_idx + 1:end_idx]).strip()
            
            clean_title = chapter_splitter.safe_filename_part(title)
            seq_num = pos + 1
            filename = f'Chapter {seq_num:04d} {clean_title}.md' if clean_title else f'Chapter {seq_num:04d}.md'
            out_path = novel_split_dir / filename
            out_path.write_text(f'# {original_heading}\n\n{body}\n', encoding='utf-8')
                
        print(f"✅ Đã tách xong {len(chapters)} chương vào: {novel_split_dir}")
        
        # Khởi tạo Pipeline Dịch
        print(f"[SourceManager] Chuyển giao sang Pipeline Manager cho: {novel_id}")
        novel_out_dir = self.output_dir / novel_id
        pipeline = PipelineManager(novel_id, str(novel_split_dir), str(novel_out_dir))
        
        # Gọi Init Stage (Quét 50 chương đầu, làm TOC, timeline)
        pipeline.init_new_novel()

    def init_novel_from_split(self, novel_id: str):
        """Khởi tạo Pipeline từ Source_Split.

        - Có metadata.json: nhánh crawl, README lấy từ metadata, entity seed 5 chương.
        - Không có metadata.json: nhánh Source_Full đã split, giữ pipeline cũ, scan 50 chương.
        """
        print(f"\n[SourceManager] Khởi tạo Pipeline từ thư mục Source_Split cho: {novel_id}")
        novel_split_dir = self.source_split_dir / novel_id
        if not novel_split_dir.exists():
            raise FileNotFoundError(f"Không tìm thấy thư mục: {novel_split_dir}")

        novel_out_dir = self.output_dir / novel_id
        is_crawled = (novel_split_dir / "metadata.json").exists()
        chapter_files = [
            p for p in novel_split_dir.glob("Chapter *.md")
            if p.is_file()
        ]
        if not chapter_files:
            chapter_files = [
                p for p in novel_split_dir.glob("*.md")
                if p.is_file() and p.name not in {"Intro.md", "README.md", "metadata.json"}
            ]
        if not chapter_files:
            print(f"⚠️ Bỏ qua init {novel_id}: Source_Split chỉ có metadata/chưa crawl xong chương.")
            return False
        pipeline = PipelineManager(
            novel_id,
            str(novel_split_dir),
            str(novel_out_dir),
            source_type="crawl" if is_crawled else "source_full",
        )
        return pipeline.init_crawled_novel() if is_crawled else pipeline.init_new_novel()

    # ==========================================
    # MẢNG 2: CRAWL TRUYỆN BẰNG PLAYWRIGHT / HTTP FALLBACK
    # ==========================================
    def _site_config_for_url(self, url: str, site_id: str = None):
        if site_id:
            return self.get_site_config(site_id)

        target = urlparse(url)
        target_host = target.netloc.lower().removeprefix("www.")
        if not target_host:
            return None

        import json
        config_path = self.base_dir / "Dashboard" / "data" / "crawl_sites.json"
        if not config_path.exists():
            return None
        with open(config_path, "r", encoding="utf-8") as f:
            sites = json.load(f).get("sites", [])

        for site in sites:
            catalog_host = urlparse(site.get("catalog_url", "")).netloc.lower().removeprefix("www.")
            if catalog_host and (target_host == catalog_host or target_host.endswith("." + catalog_host)):
                return site
        return None

    def _should_block_images(self, url: str, site_id: str = None):
        site = self._site_config_for_url(url, site_id)
        return bool(site and site.get("content_type") == "text")

    def _route_text_site_images(self, page, url: str, site_id: str = None):
        if not self._should_block_images(url, site_id):
            return

        def route_handler(route):
            if route.request.resource_type == "image":
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)


    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _metadata_from_soup(self, soup, source_url: str, site_id: str = None):
        def meta_content(*names):
            for name in names:
                tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
                if tag and tag.get("content"):
                    return tag["content"].strip()
            return ""

        title = meta_content("og:title", "twitter:title")
        if title:
            title = re.split(r"[_\-|]", title)[0]
        else:
            h1 = soup.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
        if not title and soup.title:
            title = re.split(r"[_\-|]", soup.title.get_text(" ", strip=True))[0]

        author = ""
        for selector in [".author", ".writer", ".book-author", "#author"]:
            node = soup.select_one(selector)
            if node:
                author = self._clean_text(re.sub(r"^(作者|作家)[:：\s]*", "", node.get_text(" ", strip=True)))
                if author:
                    break
        if not author:
            page_text = self._clean_text(soup.get_text(" ", strip=True))
            match = re.search(r"作者[:：\s]*([^\s/|，。]+)", page_text)
            author = match.group(1).strip() if match else ""

        description = meta_content("og:description", "description", "twitter:description")
        if not description:
            for selector in ["#intro", ".intro", ".book-intro", ".bookintro", ".description", ".desc", "#bookintro"]:
                node = soup.select_one(selector)
                if node:
                    description = self._clean_text(node.get_text(" ", strip=True))
                    if len(description) >= 20:
                        break

        cover_url = meta_content("og:image", "twitter:image")
        if not cover_url:
            for selector in [".cover img", ".book-cover img", ".bookcover img", ".book-img img", ".img_in img", "#fmimg img", "img"]:
                img = soup.select_one(selector)
                if img:
                    cover_url = img.get("src") or img.get("data-src") or img.get("data-original") or ""
                    if cover_url:
                        break
        if cover_url:
            cover_url = urljoin(source_url, cover_url)

        site = self._site_config_for_url(source_url, site_id) or {}
        return {
            "title": self._clean_text(title),
            "author": self._clean_text(author),
            "description": self._clean_text(description),
            "cover_url": cover_url,
            "source_url": source_url,
            "source_id": site_id or site.get("id", ""),
            "source_name": site.get("name", ""),
        }

    def _cover_extension(self, cover_url: str, content_type: str = ""):
        ext = ""
        if content_type:
            ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
        if not ext:
            ext = Path(urlparse(cover_url).path).suffix
        if ext.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return ".jpg" if ext.lower() == ".jpeg" else ext.lower()
        return ".jpg"

    def _download_cover(self, cover_url: str, novel_split_dir: Path):
        if not cover_url:
            return ""
        try:
            from curl_cffi import requests as http_requests
            response = http_requests.get(
                cover_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
                impersonate="chrome110",
                timeout=30,
            )
            content = response.content
            content_type = response.headers.get("content-type", "")
        except ImportError:
            import requests as http_requests
            response = http_requests.get(cover_url, timeout=30)
            content = response.content
            content_type = response.headers.get("content-type", "")
        except Exception as e:
            print(f"  ⚠️ Không tải được cover: {e}")
            return ""

        if not content or len(content) < 100:
            return ""
        ext = self._cover_extension(cover_url, content_type)
        cover_path = novel_split_dir / f"cover{ext}"
        cover_path.write_bytes(content)
        return cover_path.name

    def _save_crawl_metadata(self, novel_split_dir: Path, metadata: dict, source_url: str, site_id: str = None):
        metadata = dict(metadata or {})
        site = self._site_config_for_url(source_url, site_id) or {}
        metadata.setdefault("source_url", source_url)
        metadata.setdefault("source_id", site_id or site.get("id", ""))
        metadata.setdefault("source_name", site.get("name", ""))
        metadata["crawled_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        metadata = {k: v for k, v in metadata.items() if v not in (None, "")}

        cover_file = self._download_cover(metadata.get("cover_url", ""), novel_split_dir)
        if cover_file:
            metadata["cover_file"] = cover_file

        with open(novel_split_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"✅ Đã lưu metadata: {novel_split_dir / 'metadata.json'}")
        return metadata

    def _fetch_html(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).read_text(encoding="utf-8")

        try:
            from curl_cffi import requests as http_requests
            response = http_requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                impersonate="chrome110",
                timeout=30,
            )
        except ImportError:
            import requests as http_requests
            response = http_requests.get(url, timeout=30)

        if not getattr(response, "encoding", None):
            response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
        if _is_cloudflare_html(html):
            raise RuntimeError("Cloudflare challenge detected")
        return html

    def _get_browser_context_kwargs(self, site_id: str = None):
        return {
            "ignore_https_errors": True,
            "viewport": {"width": 1440, "height": 2200},
            "locale": "zh-CN",
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        }

    def _write_crawled_chapter(self, novel_split_dir: Path, index: int, title: str, body_text: str):
        clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()[:80]
        filename = f"Chapter {index:04d} {clean_title}.md" if clean_title else f"Chapter {index:04d}.md"
        with open(novel_split_dir / filename, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{body_text}\n")

    def _extract_chapter_links_from_soup(self, soup, base_url: str):
        selectors = ["#list dl dd a", ".box_con #list dl dd a", "#chapterlist p a", ".chapter-list li a", ".dirList li a", "ul.chapterlist li a"]
        elements = []
        for selector in selectors:
            elements = soup.select(selector)
            if len(elements) > 10:
                break
        if not elements:
            elements = [a for a in soup.find_all("a", href=True) if "第" in a.get_text(" ", strip=True) or "章" in a.get_text(" ", strip=True)]

        chapters = []
        seen = set()
        for el in elements:
            href = el.get("href")
            if not href:
                continue
            chapter_url = urljoin(base_url, href)
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapters.append({"title": el.get_text(" ", strip=True) or f"Chapter {len(chapters) + 1}", "url": chapter_url})
        return normalize_chapter_order(chapters)

    def _crawl_novel_http(self, url: str, novel_id: str, max_chapters: int = 10):
        from bs4 import BeautifulSoup

        novel_split_dir = self.source_split_dir / novel_id
        novel_split_dir.mkdir(parents=True, exist_ok=True)

        toc_url = url[:-4] + "/" if (url or "").endswith(".htm") else url
        html = self._fetch_html(toc_url)
        soup = BeautifulSoup(html, "html.parser")
        self._save_crawl_metadata(novel_split_dir, self._metadata_from_soup(soup, url), url)
        chapters = self._extract_chapter_links_from_soup(soup, toc_url)
        if not chapters:
            raise ValueError("Không tìm thấy danh sách chương.")

        total = min(len(chapters), max_chapters)
        print(f"Đã lấy được danh sách {len(chapters)} chương bằng HTTP fallback. Đang tải {total} chương...")
        content_selectors = ["#content", "#nr_body", ".Readarea", ".read-content", "#chaptercontent", ".panel-body"]

        for i, chapter in enumerate(chapters[:max_chapters], 1):
            title = chapter["title"]
            chapter_html = self._fetch_html(chapter["url"])
            chapter_soup = BeautifulSoup(chapter_html, "html.parser")
            content = None
            for selector in content_selectors:
                content = chapter_soup.select_one(selector)
                if content:
                    break
            body_text = content.get_text("\n", strip=True) if content else chapter_soup.get_text("\n", strip=True)
            body_text = "\n".join(line.strip() for line in body_text.splitlines() if line.strip())
            self._write_crawled_chapter(novel_split_dir, i, title, body_text)

        print(f"✅ Đã crawl xong {total} chương vào: {novel_split_dir}")

    def crawl_novel_playwright(self, url: str, novel_id: str, max_chapters: int = 10, site_id: str = None):
        """Crawl truyện từ web vào Source_Split, dùng Playwright nếu có và fallback HTTP nếu browser không chạy được."""
        print(f"\n[SourceManager] Bắt đầu Crawl web: {url} cho {novel_id}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("⚠️ Playwright chưa được cài đặt. Chuyển sang HTTP fallback.")
            return self._crawl_novel_http(url, novel_id, max_chapters)

        novel_split_dir = self.source_split_dir / novel_id
        novel_split_dir.mkdir(parents=True, exist_ok=True)
        toc_url = url[:-4] + "/" if (url or "").endswith(".htm") else url

        try:
            with sync_playwright() as p:
                browser = _launch_chromium(p)
                try:
                    page = browser.new_page(**self._get_browser_context_kwargs(site_id))
                    self._route_text_site_images(page, toc_url, site_id)
                    print("Đang mở trang mục lục...")
                    page.goto(toc_url, timeout=90000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    page_html = page.content()
                    if _is_cloudflare_html(page_html):
                        raise RuntimeError("Cloudflare challenge detected in Playwright page")
                    try:
                        from bs4 import BeautifulSoup
                        meta = self._metadata_from_soup(BeautifulSoup(page_html, "html.parser"), url, site_id)
                        if meta.get("title") or meta.get("description"):
                            self._save_crawl_metadata(novel_split_dir, meta, url, site_id)
                    except Exception as meta_err:
                        print(f"  ⚠️ Không lưu được metadata: {meta_err}")

                    print("Đang phân tích cấu trúc trang mục lục...")
                    selectors = ["#list dl dd a", ".box_con #list dl dd a", "#chapterlist p a", ".chapter-list li a", ".dirList li a", "ul.chapterlist li a"]
                    elements = []
                    for sel in selectors:
                        elements = page.query_selector_all(sel)
                        if len(elements) > 10:
                            print(f"Tìm thấy {len(elements)} chương với selector: {sel}")
                            break

                    if not elements:
                        for link in page.query_selector_all("a"):
                            href = link.get_attribute("href")
                            text = link.inner_text().strip()
                            if href and ("/" in href or ".html" in href) and ("第" in text or "章" in text):
                                elements.append(link)

                    chapters = []
                    seen = set()
                    for el in elements:
                        href = el.get_attribute("href")
                        if not href:
                            continue
                        chapter_url = urljoin(toc_url, href)
                        if chapter_url in seen:
                            continue
                        seen.add(chapter_url)
                        chapters.append({"title": el.inner_text().strip() or f"Chapter {len(chapters) + 1}", "url": chapter_url})
                    chapters = normalize_chapter_order(chapters)

                    if not chapters:
                        print("❌ Không tìm thấy danh sách chương.")
                        return

                    total = min(len(chapters), max_chapters)
                    print(f"Đã lấy được danh sách {len(chapters)} chương. Đang tải nội dung {total} chương...")
                    import random
                    import time

                    for i, chapter in enumerate(chapters[:max_chapters], 1):
                        try:
                            title = chapter["title"]
                            print(f"  [{i}/{total}] Đang tải: {title}")
                            chap_page = browser.new_page(**self._get_browser_context_kwargs(site_id))
                            self._route_text_site_images(chap_page, chapter["url"], site_id)
                            try:
                                chap_page.goto(chapter["url"], timeout=60000, wait_until="domcontentloaded")
                                chap_page.wait_for_timeout(1500)
                                if _is_cloudflare_html(chap_page.content()):
                                    raise RuntimeError("Cloudflare challenge detected on chapter page")
                                body_text = ""
                                for c_sel in ["#content", "#nr_body", ".Readarea", ".read-content", "#chaptercontent", ".panel-body"]:
                                    c_el = chap_page.query_selector(c_sel)
                                    if c_el:
                                        body_text = c_el.inner_text()
                                        break
                                if not body_text:
                                    body_text = chap_page.inner_text("body")
                                body_text = "\n".join(part.strip() for part in body_text.split("\n") if part.strip())
                                self._write_crawled_chapter(novel_split_dir, i, title, body_text)
                            finally:
                                chap_page.close()
                            time.sleep(random.uniform(1.0, 3.0))
                        except Exception as e:
                            print(f"  ❌ Lỗi tải chương {i}: {e}")
                finally:
                    browser.close()
        except Exception as e:
            print(f"⚠️ Playwright không chạy được ({e}). Chuyển sang HTTP fallback.")
            return self._crawl_novel_http(url, novel_id, max_chapters)

        print(f"✅ Đã crawl xong {total} chương vào: {novel_split_dir}")
        print("💡 Gợi ý: Bạn có thể chạy SourceManager.split_and_init_novel() với mode tuỳ chỉnh để khởi tạo Pipeline sau khi crawl.")

    def crawl_novel_via_plugin(self, url: str, novel_id: str, site_id: str, max_chapters: int = 10):
        """Crawl truyện bằng hệ thống Plugin mở rộng (hỗ trợ cả JSON và Python scripts)"""
        print(f"\n[SourceManager] Bắt đầu Crawl web qua Plugin: {url} cho {novel_id} (Nguồn: {site_id})")
        
        # Load Plugin
        import sys
        if str(self.base_dir / "Script") not in sys.path:
            sys.path.append(str(self.base_dir / "Script"))
            
        from plugin_manager import PluginManager
        pm = PluginManager(str(self.base_dir))
        plugin = pm.get_plugin(site_id)
        
        if not plugin:
            print(f"❌ Không tìm thấy Extension/Plugin cho nguồn: {site_id}")
            return
            
        novel_split_dir = self.source_split_dir / novel_id
        novel_split_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            print(f"Đang gọi Plugin [{plugin.source_name}] lấy metadata...")
            try:
                self._save_crawl_metadata(novel_split_dir, plugin.get_metadata(url), url, site_id)
            except Exception as meta_err:
                print(f"  ⚠️ Không lưu được metadata: {meta_err}")

            print(f"Đang gọi Plugin [{plugin.source_name}] lấy mục lục...")
            chapters = normalize_chapter_order(plugin.get_toc(url))
            if not chapters:
                print("❌ Plugin không tìm thấy danh sách chương.")
                return
                
            total = min(len(chapters), max_chapters)
            print(f"✅ Đã tìm thấy {len(chapters)} chương. Tiến hành cào {total} chương...")
            self.crawl_jobs[novel_id] = {'status': 'running', 'progress': 0, 'total': total, 'current_chap': ''}
            
            import time
            import random
            for i, chap in enumerate(chapters[:max_chapters], 1):
                while self.crawl_jobs.get(novel_id, {}).get('status') == 'paused':
                    time.sleep(1)
                if self.crawl_jobs.get(novel_id, {}).get('status') == 'cancelled':
                    break
                    
                title = chap['title']
                link = chap['url']
                self.crawl_jobs[novel_id]['progress'] = i
                self.crawl_jobs[novel_id]['current_chap'] = title
                
                print(f"  [{i}/{total}] Đang tải: {title}")
                body_text = plugin.get_chapter(link)
                
                if not body_text:
                    print(f"  ⚠️ Lỗi lấy nội dung chương {i}.")
                    continue
                    
                # Clean filename
                clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"Chapter {i:04d} {clean_title}.md"
                
                with open(novel_split_dir / filename, 'w', encoding='utf-8') as f:
                    f.write(f"# {title}\n\n{body_text}\n")
                    
                delay = random.uniform(2.0, 5.0)
                time.sleep(delay)
                
            print(f"\n✅ Đã hoàn tất crawl {total} chương bằng Plugin hệ mới.")
            if self.crawl_jobs.get(novel_id, {}).get('status') != 'cancelled':
                self.crawl_jobs[novel_id]['status'] = 'completed'
                
        except Exception as e:
            print(f"Lỗi crawl qua Plugin: {e}")
            if novel_id in self.crawl_jobs:
                self.crawl_jobs[novel_id]['status'] = 'error'

    def get_site_config(self, site_id: str):
        import json
        config_path = self.base_dir / "Dashboard/data/crawl_sites.json"
        if not config_path.exists():
            return None
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return next((s for s in config.get('sites', []) if s['id'] == site_id), None)

    def get_site_categories(self, site_id: str):
        """Trích xuất động danh sách chuyên mục/thể loại từ trang chủ."""
        site_config = self.get_site_config(site_id)
        if not site_config:
            raise ValueError(f"Không tìm thấy cấu hình cho site {site_id}")
            
        base_url = site_config.get('catalog_url', '')
        # Nếu url là trang con, lấy domain gốc
        from urllib.parse import urlparse, urljoin
        from curl_cffi import requests
        from bs4 import BeautifulSoup
        import re
        
        parsed = urlparse(base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2"
        }
        
        try:
            response = requests.get(homepage, headers=headers, impersonate="chrome110", timeout=15)
        except Exception as e:
            return [{"name": f"Lỗi: {e}", "url": homepage}]
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Tìm menu (nav)
        nav_elements = soup.find_all(['nav', 'div', 'ul'], class_=re.compile(r'nav|menu|header', re.I))
        
        categories = []
        seen_urls = set()
        
        for nav in nav_elements:
            for a in nav.find_all('a', href=True):
                name = a.text.strip()
                href = a['href']
                if not name or len(name) > 10 or 'javascript' in href or '#' in href:
                    continue
                full_url = urljoin(homepage, href)
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    categories.append({"name": name, "url": full_url})
                    
        # Nếu không tìm thấy qua class, lấy bừa các link ở top body
        if not categories:
            for a in soup.find_all('a', href=True)[:30]:
                name = a.text.strip()
                if name and len(name) <= 8 and ('/sort' in a['href'] or '/fenlei' in a['href'] or '/top' in a['href'] or 'list' in a['href']):
                    full_url = urljoin(homepage, a['href'])
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        categories.append({"name": name, "url": full_url})
                        
        return categories

    def get_novels_from_category(self, site_id: str, category_url: str):
        """Cào danh sách truyện từ 1 category url."""
        site_config = self.get_site_config(site_id)
        if not site_config:
            return []
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }
        
        from curl_cffi import requests
        from bs4 import BeautifulSoup
        try:
            response = requests.get(category_url, headers=headers, impersonate="chrome110", timeout=15)
        except Exception as e:
            return [{"title": f"Lỗi: {e}", "url": "", "author": ""}]
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        sels = site_config.get('selectors', {})
        items = soup.select(sels.get('novel_item', 'li'))
        
        novels = []
        from urllib.parse import urljoin
        for item in items:
            a_tag = item.select_one(sels.get('title', 'a'))
            if not a_tag:
                continue
            title = a_tag.text.strip()
            url_tag = item.select_one(sels.get('url', sels.get('title', 'a'))) or a_tag
            url = urljoin(category_url, url_tag.get('href', ''))
            
            author_tag = item.select_one(sels.get('author', '.author'))
            author = author_tag.text.strip() if author_tag else "Unknown"
            
            if title and url and len(title) > 0 and len(title) < 50:
                novels.append({"title": title, "url": url, "author": author})
        
        # Heuristic fallback if standard selectors yield poor results
        valid_novels = [n for n in novels if len(n['title']) >= 2]
        if len(valid_novels) < 3:
            novels = []
            seen = set()
            ignore_texts = {'首页', '排行', '书架', '分类', '全本', '完本', '记录', '登录', '注册', '书库', '男生', '女生', '历史', '玄幻', '都市', '仙侠', '科幻', '网游', '小说', '繁体', '简体', '搜索', '帮助', '点击阅读', '加入书架', '目录'}
            import re
            for a in soup.find_all('a'):
                href = a.get('href', '')
                title = a.text.strip()
                if not href or not title or len(title) < 2 or len(title) > 30: continue
                if any(it in title for it in ignore_texts): continue
                
                # Strict novel URL pattern matching:
                # Matches: /book/123, /info/123, /b/123, /123.html, /12_34.htm
                is_novel_link = False
                if re.search(r'/(book|info|b|xiaoshuo|xs)/', href): is_novel_link = True
                elif re.search(r'/\d+(_\d+)?\.html?$', href): is_novel_link = True
                elif re.search(r'/\d+/$', href) and not re.search(r'/(class|sort|list|fenlei)/', href): is_novel_link = True
                
                if is_novel_link:
                    # Clean title (remove newlines and status tags like 连载, 全本)
                    title = re.sub(r'(\n|连载|全本|完结|阅读|最新).*', '', title).strip()
                    if len(title) < 2: continue
                    
                    full_url = urljoin(category_url, href)
                    if full_url not in seen:
                        seen.add(full_url)
                        novels.append({"title": title, "url": full_url, "author": "Unknown"})
                
        return novels[:15]

if __name__ == '__main__':
    import os
    mgr = SourceManager("/sdcard/My Agent/Translator Engine")
    
    # Chuẩn bị file text giả lập để test split
    mgr.source_full_dir.mkdir(parents=True, exist_ok=True)
    sample_txt = mgr.source_full_dir / "test_novel.txt"
    if not sample_txt.exists():
        with open(sample_txt, 'w', encoding='utf-8') as f:
            f.write("Giới thiệu truyện: Một siêu phẩm giả tưởng.\n\n")
            f.write("第一章 Bắt đầu\nNội dung chương 1...\n\n")
            f.write("第二章 Phát triển\nNội dung chương 2...\n\n")
            f.write("第三章 Kết thúc\nNội dung chương 3...\n")
            
    print("--- TEST MẢNG 1 (Split & Init) ---")
    mgr.split_and_init_novel("novel_test_01", "test_novel.txt")
    
    print("\n--- TEST MẢNG 2 (Crawl) ---")
    print("Mảng 2 đã được chuẩn bị sẵn framework.")
