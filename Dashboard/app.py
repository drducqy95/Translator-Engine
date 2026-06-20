from flask import Flask, render_template, jsonify, request
import json
import threading
from pathlib import Path
import sys

app = Flask(__name__)
DATA_DIR = Path(__file__).parent / "data"

# Ensure initial data file exists
if not (DATA_DIR / "discovered_novels.json").exists():
    with open(DATA_DIR / "discovered_novels.json", 'w') as f:
        json.dump([], f)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/novels')
def get_novels():
    discovered_file = DATA_DIR / "discovered_novels.json"
    if discovered_file.exists():
        with open(discovered_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify(data)
    return jsonify([])

@app.route('/api/scan', methods=['POST'])
def trigger_scan():
    import crawl_scanner
    threading.Thread(target=crawl_scanner.scan_all_sites).start()
    return jsonify({"status": "Scanning started in background. Please refresh in a few seconds."})

@app.route('/api/crawl', methods=['POST'])
def trigger_crawl():
    req = request.json
    novel_id = req.get('id')
    url = req.get('url')
    
    _update_novel_status(novel_id, "crawling")
    threading.Thread(target=_run_crawl_job, args=(novel_id, url)).start()
    return jsonify({"status": "Crawl job queued"})

def _update_novel_status(novel_id, status):
    discovered_file = DATA_DIR / "discovered_novels.json"
    with open(discovered_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for d in data:
        if d['id'] == novel_id:
            d['status'] = status
    with open(discovered_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _run_crawl_job(novel_id, url):
    # Setup path to import source_manager
    sys.path.append(str(Path(__file__).parent.parent / "Script"))
    from source_manager import SourceManager
    
    base_dir = str(Path(__file__).parent.parent)
    mgr = SourceManager(base_dir)
    try:
        # Giới hạn 5 chương cho test
        mgr.crawl_novel_playwright(url, novel_id, max_chapters=5)
        # Khởi tạo pipeline
        mgr.init_novel_from_split(novel_id)
        _update_novel_status(novel_id, "done")
    except Exception as e:
        print("Lỗi Crawl:", e)
        _update_novel_status(novel_id, "error")

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
