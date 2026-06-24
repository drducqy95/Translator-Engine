import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from Bot.config import logger, load_settings, engine_dir, source_mgr
from Bot import crawl_queue
from pipeline_manager import PipelineManager

_daemon_threads = []
PROCESSING_TIMEOUT_SECONDS = 60 * 60
TRANSLATION_MAX_BRANCHES = 4
CRAWL_CYCLE_SECONDS = 60
_translation_cursor = 0

def _load_toc(toc_path):
    with open(toc_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_toc(toc_path, toc):
    with open(toc_path, "w", encoding="utf-8") as f:
        json.dump(toc, f, ensure_ascii=False, indent=4)

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
    """Mỗi 5 phút claim tối đa 1 job crawl trong queue."""
    while True:
        try:
            if not load_settings().get("daemon_crawl", True):
                time.sleep(30)
                continue

            job = crawl_queue.claim_next_job()
            if job:
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
                    if not source_mgr.init_novel_from_split(novel_id):
                        raise RuntimeError("Khởi tạo pipeline crawl thất bại")
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
        except Exception as e:
            logger.info(f"[Daemon Crawl] Lỗi: {e}")
        time.sleep(CRAWL_CYCLE_SECONDS)

def daemon_project_init():
    """Mỗi 5 phút: Quét Source_Split, nếu chưa có project trong Output -> Chạy Init pipeline."""
    while True:
        try:
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
                chapter["status"] = "done" if success else "pending"
                chapter["error"] = err if not success else ""
                chapter.pop("processing_started_at", None)
        _save_toc(toc_path, toc)

def daemon_pipeline_executor():
    """Mỗi vòng dispatch tối đa 4 branch dịch, round-robin mỗi branch 1 chương."""
    global _translation_cursor
    executor = ThreadPoolExecutor(max_workers=TRANSLATION_MAX_BRANCHES)
    active = {}
    first_scan = True

    def process_task(novel_id, chapter_name):
        logger.info(f"[Daemon Pipeline] Bắt đầu dịch: {novel_id} - {chapter_name}")
        pm = PipelineManager(novel_id, str(engine_dir / "Source_Split" / novel_id), str(engine_dir / "Output" / novel_id))
        success, err = pm.process_chapter(chapter_name)
        _finish_task(novel_id, chapter_name, success, err)
        if not success:
            logger.info(f"[Daemon Pipeline] Lỗi tại {novel_id}/{chapter_name}: {err[:300]}")

    while True:
        try:
            if not load_settings().get("daemon_pipeline", True):
                time.sleep(30)
                continue

            active = {future: meta for future, meta in active.items() if not future.done()}
            active_projects = {meta[0] for meta in active.values()}
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
                        if isinstance(c, dict) and c.get("status") == "pending" and c.get("file", c.get("name", ""))
                    ]
                    if pending_chaps:
                        project_rows.append((novel_id, pending_chaps))

            capacity = max(0, TRANSLATION_MAX_BRANCHES - len(active))
            tasks, _translation_cursor = _select_round_robin_tasks(
                project_rows,
                active_projects=active_projects,
                capacity=capacity,
                cursor=_translation_cursor,
            )

            for novel_id, chapter_name in tasks:
                if _claim_task(novel_id, chapter_name):
                    future = executor.submit(process_task, novel_id, chapter_name)
                    active[future] = (novel_id, chapter_name)
            first_scan = False
        except Exception as e:
            logger.info(f"[Daemon Pipeline] Lỗi: {e}")
            first_scan = False
        time.sleep(120)

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
