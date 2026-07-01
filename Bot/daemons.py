import time
import json
import threading
import os
import re
from concurrent.futures import ThreadPoolExecutor
from Bot.config import logger, load_settings, engine_dir, source_mgr
from Bot import crawl_queue
from pipeline_manager import PipelineManager

_daemon_threads = []
PROCESSING_TIMEOUT_SECONDS = 60 * 60
TRANSLATION_MAX_BRANCHES = 4
CRAWL_CYCLE_SECONDS = 60
_translation_cursor = 0
PIPELINE_HEARTBEAT = engine_dir / "Temp" / "pipeline_heartbeat.json"
PIPELINE_LOG = engine_dir / "logs" / "pipeline_daemon.log"

def _write_pipeline_heartbeat(payload):
    try:
        PIPELINE_HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        tmp = PIPELINE_HEARTBEAT.with_name('.pipeline_heartbeat.json.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, PIPELINE_HEARTBEAT)
    except Exception:
        pass

def _log_pipeline(msg):
    try:
        PIPELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PIPELINE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def _load_toc(toc_path):
    with open(toc_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_toc(toc_path, toc):
    tmp_path = toc_path.with_name(f".{toc_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(toc, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, toc_path)

def _chapter_index(name):
    match = re.search(r"(?:Chapter|Chương)\s*0*([0-9]+)", name or "", re.IGNORECASE)
    return int(match.group(1)) if match else None

def _chapter_sort_key(path):
    idx = _chapter_index(path.name)
    return (0, idx, path.name) if idx is not None else (1, path.name)

def _source_chapter_files(novel_id):
    source_dir = engine_dir / "Source_Split" / novel_id
    if not source_dir.exists():
        return []
    files = [p for p in source_dir.glob("Chapter *.md") if p.is_file()]
    if not files:
        files = [p for p in source_dir.glob("*.md") if p.is_file() and p.name not in {"Intro.md", "README.md", "metadata.json"}]
    return sorted(files, key=_chapter_sort_key)

def _repair_toc_from_source(novel_id):
    files = _source_chapter_files(novel_id)
    if not files:
        return False
    toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
    final_dir = engine_dir / "Output" / novel_id / "Final_Translated"
    toc_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        toc = _load_toc(toc_path) if toc_path.exists() and toc_path.stat().st_size > 0 else {}
    except Exception:
        toc = {}
    old_rows = {}
    for row in toc.get("chapters", []) if isinstance(toc, dict) else []:
        key = row.get("file", row.get("name")) if isinstance(row, dict) else None
        if key:
            old_rows[key] = row
    translated_by_idx = {}
    if final_dir.exists():
        for path in final_dir.glob("*.md"):
            idx = _chapter_index(path.name)
            if idx:
                translated_by_idx[idx] = path.name
    chapters = []
    changed = False
    for fallback_idx, path in enumerate(files, 1):
        idx = _chapter_index(path.name) or fallback_idx
        row = dict(old_rows.get(path.name, {}))
        if row.get("file") != path.name:
            row["file"] = path.name
            changed = True
        row["index"] = idx
        translated = translated_by_idx.get(idx)
        if translated:
            row["status"] = "done"
            row["translated_file"] = translated
            row.pop("processing_started_at", None)
        else:
            if row.get("status") in {"processing", "done"}:
                row["status"] = "pending"
                row.pop("translated_file", None)
                row.pop("processing_started_at", None)
                changed = True
            row.setdefault("status", "pending")
        chapters.append(row)
    if toc.get("chapters") != chapters:
        changed = True
    toc = toc if isinstance(toc, dict) else {}
    toc.setdefault("novel_id", novel_id)
    toc.setdefault("source_type", "crawl")
    toc["chapters"] = chapters
    if changed:
        _save_toc(toc_path, toc)
    return changed

def _crawl_error_is_temporary(error):
    text = (error or "").lower()
    permanent_markers = (
        "cloudflare challenge",
        "không tìm thấy danh sách chương",
        "khong tim thay danh sach chuong",
        "just a moment",
        "enable javascript and cookies",
    )
    return not any(marker in text for marker in permanent_markers)


def _requeue_incomplete_crawls():
    try:
        items = crawl_queue.load_queue()
        changed = False
        now = int(time.time())
        for item in items:
            if item.get("status") not in {"done", "error"}:
                continue
            if item.get("status") == "error":
                if int(item.get("retry_at") or 0) > now:
                    continue
                if int(item.get("attempt_count") or 0) >= 3 and not _crawl_error_is_temporary(item.get("error")):
                    item["status"] = "blocked"
                    item["error"] = f"Blocked after repeated crawl failure: {item.get('error', '')}"[:500]
                    item["updated_at"] = now
                    changed = True
                    continue
            novel_id = item.get("novel_id")
            source_dir = engine_dir / "Source_Split" / novel_id
            if not novel_id or not source_dir.exists():
                continue
            last_idx = max((_chapter_index(p.name) or 0 for p in source_dir.glob("Chapter *.md")), default=0)
            if last_idx and item.get("max_chapters") in (None, "", 0, "0", "all"):
                end = item.get("end_chapter")
                if not end or last_idx < int(end):
                    item["status"] = "queued"
                    item["start_chapter"] = last_idx + 1
                    item["error"] = f"Auto-resume incomplete crawl from chapter {last_idx + 1}"
                    item["updated_at"] = now
                    item.pop("finished_at", None)
                    changed = True
        if changed:
            crawl_queue.save_queue(items)
    except Exception as exc:
        logger.info(f"[Daemon Crawl] Không requeue được crawl incomplete: {exc}")

def _recover_stale_processing(toc, force=False):
    now = time.time()
    changed = False
    for chapter in toc.get("chapters", []):
        if chapter.get("status") != "processing":
            continue
        started = chapter.get("processing_started_at")
        if force or not started or now - float(started) > PROCESSING_TIMEOUT_SECONDS:
            chapter["status"] = "pending"
            chapter["error"] = "Recovered stale processing task"
            chapter.pop("processing_started_at", None)
            changed = True
    return changed


def _select_round_robin_tasks(project_rows, active_projects=None, capacity=TRANSLATION_MAX_BRANCHES, cursor=0):
    active_projects = set(active_projects or [])
    eligible = [row for row in project_rows if row[1] and row[0] not in active_projects]
    if not eligible or capacity <= 0:
        return [], cursor

    start = cursor % len(eligible)
    ordered = eligible[start:] + eligible[:start]
    tasks = []
    for novel_id, pending_chaps in ordered:
        if len(tasks) >= capacity:
            break
        tasks.append((novel_id, pending_chaps[0]))

    new_cursor = (start + len(tasks)) % len(eligible) if eligible else cursor
    return tasks, new_cursor


def _select_serial_project_task(project_rows, current_project=None):
    if not project_rows:
        return None
    if current_project:
        for novel_id, pending_chaps in project_rows:
            if novel_id == current_project and pending_chaps:
                return novel_id, pending_chaps[0]
    for novel_id, pending_chaps in project_rows:
        if pending_chaps:
            return novel_id, pending_chaps[0]
    return None

def _project_runnable(novel_id, project_locks, lock_enabled=True):
    if not lock_enabled:
        return True
    if not isinstance(project_locks, dict) or not project_locks:
        return False
    # Selected-project mode: True = allow/run, False/missing = block.
    if any(value is True for value in project_locks.values()):
        return project_locks.get(novel_id) is True
    # Legacy fallback: if no explicit True exists, keep old meaning for safety.
    return project_locks.get(novel_id) is not False

def _mark_discovered_status(novel_id, status):
    path = engine_dir / "Dashboard" / "data" / "discovered_novels.json"
    if not path.exists():
        return
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for item in items if isinstance(items, list) else []:
            if item.get("id") == novel_id:
                item["status"] = status
                changed = True
                break
        if changed:
            path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.info(f"[Daemon Crawl] Không cập nhật được discovered status: {exc}")


def _has_chapter_files(novel_dir):
    if not novel_dir.exists() or not novel_dir.is_dir():
        return False
    chapter_files = [p for p in novel_dir.glob("Chapter *.md") if p.is_file()]
    if chapter_files:
        return True
    return any(
        p.is_file() and p.name not in {"Intro.md", "README.md", "metadata.json"}
        for p in novel_dir.glob("*.md")
    )

def daemon_raw_processing():
    """Mỗi 5 phút: Quét Source_Full, tạo thư mục Source_Split và tách chương."""
    while True:
        try:
            if not load_settings().get("daemon_raw", True):
                time.sleep(30)
                continue

            full_dir = engine_dir / "Source_Full"
            split_dir = engine_dir / "Source_Split"
            processed_dir = engine_dir / "Source_Full" / "processed"
            if full_dir.exists():
                processed_dir.mkdir(exist_ok=True)
                files = []
                for ext in ["*.txt", "*.html", "*.epub", "*.docx", "*.md"]:
                    files.extend(list(full_dir.glob(ext)))

                for txt_file in files:
                    novel_id = txt_file.stem
                    novel_split_dir = split_dir / novel_id
                    if not novel_split_dir.exists():
                        logger.info(f"[Daemon Raw] Đang băm chương truyện: {novel_id}")
                        source_mgr.split_and_init_novel(novel_id, txt_file.name)
                        import shutil
                        shutil.move(str(txt_file), str(processed_dir / txt_file.name))
        except Exception as e:
            logger.info(f"[Daemon Raw] Lỗi: {e}")
        time.sleep(300)

def daemon_crawl_executor():
    """Claim job crawl theo số luồng cấu hình trong Temp/settings.json."""
    executor = ThreadPoolExecutor(max_workers=32)
    active = {}

    def run_crawl_job(job):
        novel_id = job.get("novel_id")
        logger.info(f"[Daemon Crawl] Bắt đầu crawl: {novel_id}")
        source_mgr.crawl_jobs[novel_id] = {
            "status": "running",
            "progress": 0,
            "total": job.get("max_chapters") or 0,
            "current_chap": job.get("title", ""),
        }
        try:
            _mark_discovered_status(novel_id, "crawling")
            source_mgr.crawl_novel_playwright(
                job.get("url"),
                novel_id,
                max_chapters=job.get("max_chapters"),
                site_id=job.get("site_id") or None,
                start_chapter=job.get("start_chapter"),
                end_chapter=job.get("end_chapter"),
            )
            source_mgr.crawl_jobs[novel_id]["status"] = "completed"
            crawl_queue.finish_job(job.get("job_id"), "done")
            _mark_discovered_status(novel_id, "done")
            logger.info(f"[Daemon Crawl] Hoàn tất crawl: {novel_id}")
        except Exception as exc:
            source_mgr.crawl_jobs[novel_id]["status"] = "error"
            source_mgr.crawl_jobs[novel_id]["error"] = str(exc)
            crawl_queue.finish_job(job.get("job_id"), "error", str(exc))
            _mark_discovered_status(novel_id, "error")
            logger.exception(f"[Daemon Crawl] Lỗi crawl {novel_id}")

    while True:
        try:
            _requeue_incomplete_crawls()
            settings = load_settings()
            if not settings.get("daemon_crawl", settings.get("crawl_enabled", True)) or settings.get("crawl_paused", False):
                time.sleep(30)
                continue

            active = {future: job for future, job in active.items() if not future.done()}
            capacity = max(0, int(settings.get("crawl_workers", 2) or 2) - len(active))
            for _ in range(capacity):
                job = crawl_queue.claim_next_job()
                if not job:
                    break
                active[executor.submit(run_crawl_job, job)] = job
        except Exception as e:
            logger.info(f"[Daemon Crawl] Lỗi: {e}")
        time.sleep(CRAWL_CYCLE_SECONDS)

def daemon_project_init():
    """Mỗi 5 phút: Quét Source_Split, nếu chưa có project trong Output -> Chạy Init pipeline."""
    while True:
        try:
            _requeue_incomplete_crawls()
            if not load_settings().get("daemon_init", True):
                time.sleep(30)
                continue

            split_dir = engine_dir / "Source_Split"
            out_dir = engine_dir / "Output"
            if split_dir.exists():
                for novel_dir in split_dir.iterdir():
                    if novel_dir.is_dir():
                        novel_id = novel_dir.name
                        toc_path = out_dir / novel_id / "State" / "toc.json"
                        if not toc_path.exists():
                            if not _has_chapter_files(novel_dir):
                                logger.info(f"[Daemon Init] Bỏ qua {novel_id}: chưa có file chương.")
                                continue
                            logger.info(f"[Daemon Init] Đang khởi tạo dự án: {novel_id}")
                            source_mgr.init_novel_from_split(novel_id)
        except Exception as e:
            logger.info(f"[Daemon Init] Lỗi: {e}")
        time.sleep(300)

def _claim_task(novel_id, chapter_name):
    import lock_mgr
    toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
    with lock_mgr.file_lock:
        toc = _load_toc(toc_path)
        for chapter in toc.get("chapters", []):
            if chapter.get("file", chapter.get("name")) == chapter_name and chapter.get("status") == "pending":
                chapter["status"] = "processing"
                chapter["processing_started_at"] = time.time()
                chapter["error"] = ""
                _save_toc(toc_path, toc)
                return True
    return False

def _finish_task(novel_id, chapter_name, success, err):
    import lock_mgr
    toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
    with lock_mgr.file_lock:
        toc = _load_toc(toc_path)
        for chapter in toc.get("chapters", []):
            if chapter.get("file", chapter.get("name")) == chapter_name:
                if success:
                    chapter["status"] = "done"
                    chapter["error"] = ""
                    chapter.pop("fail_count", None)
                else:
                    fail_count = int(chapter.get("fail_count") or 0) + 1
                    chapter["fail_count"] = fail_count
                    chapter["error"] = err if not success else ""
                    chapter["status"] = "blocked" if fail_count >= 3 else "pending"
                chapter.pop("processing_started_at", None)
        _save_toc(toc_path, toc)

def daemon_pipeline_executor():
    """Mỗi vòng dispatch tối đa 4 branch dịch, round-robin mỗi branch 1 chương."""
    global _translation_cursor
    executor = ThreadPoolExecutor(max_workers=32)
    active = {}
    first_scan = True
    current_project = None

    def process_task(novel_id, chapter_name):
        logger.info(f"[Daemon Pipeline] Bắt đầu dịch: {novel_id} - {chapter_name}")
        _log_pipeline(f"start {novel_id} {chapter_name}")
        _write_pipeline_heartbeat({"state": "processing", "novel_id": novel_id, "chapter": chapter_name, "updated_at": time.time()})
        try:
            import sys
            sys.stdout.flush()
        except Exception:
            pass
        pm = PipelineManager(novel_id, str(engine_dir / "Source_Split" / novel_id), str(engine_dir / "Output" / novel_id))
        success, err = False, ""
        for attempt in range(1, 4):
            success, err = pm.process_chapter(chapter_name)
            if success:
                break
            logger.info(f"[Daemon Pipeline] Retry {attempt}/3 cho {novel_id}/{chapter_name}: {str(err)[:160]}")
            time.sleep(5 * attempt)
        _finish_task(novel_id, chapter_name, success, err)
        if not success:
            logger.info(f"[Daemon Pipeline] Lỗi tại {novel_id}/{chapter_name}: {err[:300]}")
            _log_pipeline(f"finish-fail {novel_id} {chapter_name} err={err[:300]}")
        else:
            _log_pipeline(f"finish-ok {novel_id} {chapter_name}")
        _write_pipeline_heartbeat({"state": "idle" if not active else "active", "updated_at": time.time()})

    while True:
        try:
            _write_pipeline_heartbeat({"state": "loop", "updated_at": time.time()})
            # Full TOC repair is expensive on large libraries; run once after boot only.
            if first_scan:
                for pdir in (engine_dir / "Output").iterdir() if (engine_dir / "Output").exists() else []:
                    if pdir.is_dir():
                        _repair_toc_from_source(pdir.name)
            settings = load_settings()
            if not settings.get("daemon_pipeline", True):
                time.sleep(30)
                continue

            active = {future: meta for future, meta in active.items() if not future.done()}
            active_projects = {meta[0] for meta in active.values()}
            lock_enabled = settings.get("pipeline_lock_enabled", True)
            project_locks = settings.get("pipeline_project_locks", {}) or {}
            max_workers = int(settings.get("pipeline_workers", TRANSLATION_MAX_BRANCHES) or TRANSLATION_MAX_BRANCHES)
            serial_mode = max_workers <= 1 or not settings.get("pipeline_round_robin", True)
            out_dir = engine_dir / "Output"
            project_rows = []

            if out_dir.exists():
                import lock_mgr
                for pdir in sorted(out_dir.iterdir(), key=lambda p: p.name.lower()):
                    toc_path = pdir / "State" / "toc.json"
                    if not pdir.is_dir() or not toc_path.exists():
                        continue
                    novel_id = pdir.name
                    with lock_mgr.file_lock:
                        toc = _load_toc(toc_path)
                        if _recover_stale_processing(toc, force=first_scan):
                            _save_toc(toc_path, toc)
                    chapters = toc.get("chapters", [])
                    pending_chaps = [
                        c.get("file", c.get("name", ""))
                        for c in chapters
                        if isinstance(c, dict)
                        and c.get("status") == "pending"
                        and int(c.get("fail_count") or 0) < 3
                        and c.get("file", c.get("name", ""))
                    ]
                    if pending_chaps:
                        # Lock semantics:
                        # - selected-project mode if any project has True: only True projects run.
                        # - fallback mode otherwise: non-False projects run.
                        if not _project_runnable(novel_id, project_locks, lock_enabled):
                            _log_pipeline(f"skip locked {novel_id}")
                            continue
                        project_rows.append((novel_id, pending_chaps))

            capacity = max(0, max_workers - len(active))
            if serial_mode and current_project and current_project not in active_projects and current_project not in {row[0] for row in project_rows}:
                current_project = None
            if serial_mode:
                task = _select_serial_project_task(project_rows, current_project=current_project)
                tasks = [task] if task and (not lock_enabled or task[0] not in active_projects) else []
            else:
                tasks, _translation_cursor = _select_round_robin_tasks(
                    project_rows,
                    active_projects=active_projects if lock_enabled else set(),
                    capacity=capacity,
                    cursor=_translation_cursor,
                )

            for novel_id, chapter_name in tasks:
                if _claim_task(novel_id, chapter_name):
                    current_project = novel_id if serial_mode else current_project
                    _write_pipeline_heartbeat({"state": "claimed", "novel_id": novel_id, "chapter": chapter_name, "updated_at": time.time()})
                    _log_pipeline(f"claimed {novel_id} {chapter_name}")
                    future = executor.submit(process_task, novel_id, chapter_name)
                    active[future] = (novel_id, chapter_name)
                else:
                    _log_pipeline(f"claim-failed {novel_id} {chapter_name}")
            first_scan = False
        except Exception as e:
            logger.info(f"[Daemon Pipeline] Lỗi: {e}")
            _log_pipeline(f"exception {e}")
            first_scan = False
        settings = load_settings()
        interval = max(10, int(settings.get("pipeline_interval_seconds", 120) or 120))
        time.sleep(interval)

def start_daemons(progress_callback=None):
    if _daemon_threads:
        return _daemon_threads
    targets = [daemon_raw_processing, daemon_crawl_executor, daemon_project_init, daemon_pipeline_executor]
    logger.info(
        "[Daemons] starting raw/crawl/init/pipeline threads; "
        "these are in-process scheduler loops, not OS cron jobs."
    )
    for target in targets:
        thread = threading.Thread(target=target, daemon=True, name=target.__name__)
        thread.start()
        _daemon_threads.append(thread)
        logger.info(f"[Daemons] started {target.__name__}")
    return _daemon_threads
