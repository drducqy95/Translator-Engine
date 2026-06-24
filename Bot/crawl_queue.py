import json
import threading
import time
from pathlib import Path

from Bot.config import engine_dir

_queue_lock = threading.RLock()
QUEUE_PATH = engine_dir / "Temp" / "crawl_queue.json"


def _now():
    return int(time.time())


def load_queue():
    with _queue_lock:
        if not QUEUE_PATH.exists():
            return []
        try:
            data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_queue(items):
    with _queue_lock:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def enqueue_job(chat_id, title, url, site_id=None, novel_id=None, max_chapters=5):
    if not url or not novel_id:
        raise ValueError("crawl job thiếu url hoặc novel_id")
    with _queue_lock:
        items = load_queue()
        for item in items:
            if item.get("novel_id") == novel_id and item.get("status") in {"queued", "running"}:
                return item, False
        job = {
            "job_id": f"{novel_id}:{_now()}",
            "chat_id": chat_id,
            "title": title or novel_id,
            "url": url,
            "site_id": site_id or "",
            "novel_id": novel_id,
            "max_chapters": int(max_chapters or 5),
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
        }
        items.append(job)
        save_queue(items)
        return job, True


def claim_next_job():
    with _queue_lock:
        items = load_queue()
        changed = False
        now = _now()
        for item in items:
            if item.get("status") == "running" and now - int(item.get("started_at") or item.get("updated_at") or 0) > 1800:
                item["status"] = "queued"
                item["error"] = "Recovered stale running crawl job"
                item["updated_at"] = now
                changed = True
        if changed:
            save_queue(items)
        if any(item.get("status") == "running" for item in items):
            return None
        for item in items:
            if item.get("status") == "queued":
                item["status"] = "running"
                item["started_at"] = _now()
                item["updated_at"] = _now()
                save_queue(items)
                return dict(item)
    return None


def finish_job(job_id, status, error=""):
    with _queue_lock:
        items = load_queue()
        for item in items:
            if item.get("job_id") == job_id:
                item["status"] = status
                item["error"] = error or ""
                item["finished_at"] = _now()
                item["updated_at"] = _now()
                break
        save_queue(items)


def stats():
    items = load_queue()
    counts = {"queued": 0, "running": 0, "done": 0, "error": 0}
    for item in items:
        status = item.get("status", "queued")
        counts[status] = counts.get(status, 0) + 1
    return counts, items
