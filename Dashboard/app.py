from flask import Flask, render_template, jsonify, request, Response
import hmac
import json
import os
import threading
from pathlib import Path
import sys
from functools import wraps

app = Flask(__name__)
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")

def check_auth(username, password):
    return (
        hmac.compare_digest(username or "", DASHBOARD_USERNAME)
        and hmac.compare_digest(password or "", DASHBOARD_PASSWORD)
    )

def authenticate():
    return Response(
    'Cần đăng nhập để sử dụng Dashboard.\n', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def get_discovered_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    discovered_file = DATA_DIR / "discovered_novels.json"
    if not discovered_file.exists():
        with open(discovered_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
    return discovered_file

@app.route('/')
@requires_auth
def index():
    return render_template('index.html')

@app.route('/api/novels')
@requires_auth
def get_novels():
    discovered_file = get_discovered_file()
    with open(discovered_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return jsonify(data)

@app.route('/api/scan', methods=['POST'])
@requires_auth
def trigger_scan():
    import crawl_scanner
    threading.Thread(target=crawl_scanner.scan_all_sites, daemon=True).start()
    return jsonify({"status": "Scanning started in background. Please refresh in a few seconds."})

@app.route('/api/crawl', methods=['POST'])
@requires_auth
def trigger_crawl():
    req = request.get_json(silent=True) or {}
    novel_id = req.get('id')
    url = req.get('url')
    site_id = req.get('site_id')
    if not novel_id or not url:
        return jsonify({"error": "Missing id or url"}), 400

    _update_novel_status(novel_id, "crawling")
    threading.Thread(target=_run_crawl_job, args=(novel_id, url, site_id), daemon=True).start()
    return jsonify({"status": "Crawl job queued"})

def _update_novel_status(novel_id, status):
    discovered_file = get_discovered_file()
    with open(discovered_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for d in data:
        if d['id'] == novel_id:
            d['status'] = status
    with open(discovered_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _run_crawl_job(novel_id, url, site_id=None):
    # Setup path to import source_manager
    sys.path.append(str(Path(__file__).parent.parent / "Script"))
    from source_manager import SourceManager
    
    base_dir = str(Path(__file__).parent.parent)
    mgr = SourceManager(base_dir)
    try:
        # Giới hạn 5 chương cho test
        mgr.crawl_novel_playwright(url, novel_id, max_chapters=5, site_id=site_id)
        # Khởi tạo pipeline
        mgr.init_novel_from_split(novel_id)
        _update_novel_status(novel_id, "done")
    except Exception as e:
        print("Lỗi Crawl:", e)
        _update_novel_status(novel_id, "error")

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
