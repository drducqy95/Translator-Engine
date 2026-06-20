import os
import re
from pathlib import Path
from pipeline_manager import PipelineManager

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
            
        # Filter duplicate consecutive headings
        filtered_chapters = []
        for i, chap in enumerate(chapters):
            if i + 1 < len(chapters):
                next_idx = chapters[i+1][3]
                body_between = "".join(lines[chap[3] + 1:next_idx]).strip()
                if not body_between:
                    continue
            filtered_chapters.append(chap)
        chapters = filtered_chapters
        
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
        """Khởi tạo Pipeline từ các file đã được crawl thẳng vào Source_Split."""
        print(f"\n[SourceManager] Khởi tạo Pipeline từ thư mục Source_Split cho: {novel_id}")
        novel_split_dir = self.source_split_dir / novel_id
        if not novel_split_dir.exists():
            raise FileNotFoundError(f"Không tìm thấy thư mục: {novel_split_dir}")
            
        novel_out_dir = self.output_dir / novel_id
        pipeline = PipelineManager(novel_id, str(novel_split_dir), str(novel_out_dir))
        pipeline.init_new_novel()

    # ==========================================
    # MẢNG 2: CRAWL TRUYỆN BẰNG PLAYWRIGHT
    # ==========================================
    def crawl_novel_playwright(self, url: str, novel_id: str, max_chapters: int = 10):
        """Dùng Playwright để crawl truyện từ web Trung Quốc, ghi thẳng vào Source_Split"""
        print(f"\n[SourceManager] Bắt đầu Crawl web: {url} cho {novel_id}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("❌ Playwright chưa được cài đặt. Vui lòng chạy: pip install playwright && playwright install")
            return
            
        novel_split_dir = self.source_split_dir / novel_id
        novel_split_dir.mkdir(parents=True, exist_ok=True)
        
        with sync_playwright() as p:
            # Ép dùng Chromium của hệ điều hành
            browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium-browser')
            page = browser.new_page()
            
            print("Đang mở trang mục lục...")
            page.goto(url, timeout=60000)
            
            # Lấy danh sách chương thực tế
            print("Đang phân tích cấu trúc trang mục lục...")
            # Thử các selector phổ biến cho mục lục tiểu thuyết TQ
            selectors = ["#list dl dd a", ".box_con #list dl dd a", ".chapter-list li a", ".dirList li a", "ul.chapterlist li a"]
            
            elements = []
            for sel in selectors:
                elements = page.query_selector_all(sel)
                if len(elements) > 10:
                    print(f"Tìm thấy {len(elements)} chương với selector: {sel}")
                    break
                    
            if not elements:
                # Fallback: tìm tất cả link có vẻ giống chương
                all_links = page.query_selector_all("a")
                for link in all_links:
                    href = link.get_attribute("href")
                    text = link.inner_text().strip()
                    if href and ("/" in href or ".html" in href) and ("第" in text or "章" in text):
                        elements.append(link)
                        
            if not elements:
                print("❌ Không tìm thấy danh sách chương.")
                browser.close()
                return

            print(f"Đã lấy được danh sách {len(elements)} chương. Đang tải nội dung {max_chapters} chương...")
            import time
            import random
            from urllib.parse import urljoin
            
            for i, el in enumerate(elements[:max_chapters], 1):
                try:
                    title = el.inner_text().strip()
                    href = el.get_attribute("href")
                    chap_url = urljoin(url, href)
                    
                    print(f"  [{i}/{max_chapters}] Đang tải: {title}")
                    chap_page = browser.new_page()
                    chap_page.goto(chap_url, timeout=30000)
                    
                    # Thử các selector phổ biến cho nội dung
                    content_sels = ["#content", ".read-content", "#chaptercontent", ".panel-body"]
                    body_text = ""
                    for c_sel in content_sels:
                        c_el = chap_page.query_selector(c_sel)
                        if c_el:
                            body_text = c_el.inner_text()
                            break
                            
                    if not body_text:
                        # Fallback
                        body_text = chap_page.inner_text("body")
                        
                    # Dọn dẹp nội dung
                    body_text = "\n".join([p.strip() for p in body_text.split('\n') if p.strip() and len(p.strip()) > 0])
                    
                    clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                    filename = f"Chapter {i:04d} {clean_title}.md"
                    
                    with open(novel_split_dir / filename, 'w', encoding='utf-8') as f:
                        f.write(f"# {title}\n\n{body_text}\n")
                        
                    chap_page.close()
                    time.sleep(random.uniform(1.0, 3.0))
                except Exception as e:
                    print(f"  ❌ Lỗi tải chương {i}: {e}")
            
            browser.close()
            
        print(f"✅ Đã crawl xong {max_chapters} chương vào: {novel_split_dir}")
        print(f"💡 Gợi ý: Bạn có thể chạy SourceManager.split_and_init_novel() với mode tuỳ chỉnh để khởi tạo Pipeline sau khi crawl.")

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
            print(f"Đang gọi Plugin [{plugin.source_name}] lấy mục lục...")
            chapters = plugin.get_toc(url)
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
            url = urljoin(category_url, a_tag.get('href', ''))
            
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
