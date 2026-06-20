import time
import json
import threading
from pathlib import Path

class Scheduler:
    def __init__(self, engine_dir: Path):
        self.engine_dir = engine_dir
        self.queue_file = engine_dir / "Temp" / "translation_queue.json"
        self.lock = threading.Lock()
        self.queue = []
        self._load_queue()

    def _load_queue(self):
        with self.lock:
            if self.queue_file.exists():
                try:
                    with open(self.queue_file, 'r', encoding='utf-8') as f:
                        self.queue = json.load(f)
                except:
                    self.queue = []

    def _save_queue(self):
        with self.lock:
            self.queue_file.parent.mkdir(exist_ok=True)
            with open(self.queue_file, 'w', encoding='utf-8') as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)

    def add_job(self, novel_id: str, chapter_file: str, priority: int = 1):
        """Thêm chương vào hàng đợi"""
        # Kiểm tra trùng
        for q in self.queue:
            if q['novel_id'] == novel_id and q['chapter'] == chapter_file:
                return False
                
        self.queue.append({
            "novel_id": novel_id,
            "chapter": chapter_file,
            "priority": priority,
            "status": "pending",
            "added_at": time.time()
        })
        self._sort_queue()
        self._save_queue()
        return True

    def _sort_queue(self):
        # Priority cao nhất (số lớn) xếp trước, thời gian thêm vào cũ hơn xếp trước
        self.queue.sort(key=lambda x: (-x['priority'], x['added_at']))

    def get_next_job(self):
        with self.lock:
            for job in self.queue:
                if job['status'] == 'pending':
                    job['status'] = 'processing'
                    self._save_queue()
                    return job
        return None

    def mark_done(self, novel_id: str, chapter_file: str, success: bool):
        with self.lock:
            for i, job in enumerate(self.queue):
                if job['novel_id'] == novel_id and job['chapter'] == chapter_file:
                    if success:
                        self.queue.pop(i)
                    else:
                        job['status'] = 'failed'
                    self._save_queue()
                    return True
        return False
        
    def list_queue(self, novel_id=None):
        if novel_id:
            return [q for q in self.queue if q['novel_id'] == novel_id]
        return self.queue
