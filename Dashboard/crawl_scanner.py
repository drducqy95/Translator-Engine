import json
import os
import random
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

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



def route_text_site_images(page, site):
    if site.get("content_type") != "text":
        return

    def route_handler(route):
        if route.request.resource_type == "image":
            route.abort()
        else:
            route.continue_()

    page.route("**/*", route_handler)


def load_sites():
    with open(DATA_DIR / "crawl_sites.json", 'r', encoding='utf-8') as f:
        return json.load(f).get("sites", [])

def scan_all_sites():
    """Dùng Playwright quét tất cả các trang mục lục để tìm truyện mới"""
    print("[CrawlScanner] Bắt đầu quét các trang mục lục...")
    sites = load_sites()
    discovered = []
    
    # Đọc danh sách cũ để không đè mất trạng thái (nếu có)
    old_data = []
    discovered_file = DATA_DIR / "discovered_novels.json"
    if discovered_file.exists():
        with open(discovered_file, 'r', encoding='utf-8') as f:
            try:
                old_data = json.load(f)
            except:
                pass
                
    old_urls = {item['url'] for item in old_data}
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            for site in sites:
                print(f"Đang quét trang: {site['name']}...")
                page = browser.new_page()
                route_text_site_images(page, site)
                try:
                    page.goto(site['catalog_url'], timeout=90000, wait_until="domcontentloaded")
                    items = page.query_selector_all(site['selectors']['novel_item'])
                    for item in items[:20]: # Giới hạn lấy 20 truyện mỗi site để demo nhanh
                        title_el = item.query_selector(site['selectors']['title'])
                        if not title_el:
                            continue
                        title = title_el.inner_text().strip()
                        url_selector = site['selectors'].get('url', site['selectors']['title'])
                        url_el = item.query_selector(url_selector) or title_el
                        url = url_el.get_attribute("href")
                        if url:
                            url = urljoin(site['catalog_url'], url)

                        if url and url not in old_urls:
                            discovered.append({
                                "id": f"novel_{int(time.time())}_{random.randint(100,999)}",
                                "site_id": site['id'],
                                "site_name": site['name'],
                                "title": title,
                                "url": url,
                                "status": "discovered",
                                "chapters_crawled": 0
                            })
                            old_urls.add(url)
                except Exception as e:
                    print(f"Lỗi khi quét {site['name']}: {e}")
                finally:
                    page.close()
            browser.close()
    except ImportError:
        print("⚠️ Playwright chưa được cài đặt. Đang sử dụng chế độ MOCK DATA để test hệ thống...")
        # Tạo dữ liệu giả lập nếu Playwright không chạy được
        for i in range(5):
            discovered.append({
                "id": f"novel_mock_{i}",
                "site_id": "biquge",
                "site_name": "BiQuGe (Bút Thú Các) - MOCK",
                "title": f"Tuyệt Thế Võ Thần Phần {i+1}",
                "url": f"https://www.biquge.com.cn/book_{i}/",
                "status": "discovered",
                "chapters_crawled": 0
            })
            
    # Gộp data mới và cũ
    final_data = old_data + discovered
    discovered_file.parent.mkdir(parents=True, exist_ok=True)
    with open(discovered_file, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Quét hoàn tất. Tìm thấy {len(discovered)} truyện mới.")
    return final_data

if __name__ == "__main__":
    scan_all_sites()
