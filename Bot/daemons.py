import time
import shutil
from pathlib import Path
import traceback
from Bot.config import logger, load_settings, engine_dir, source_mgr, pinned_messages
from pipeline_manager import PipelineManager

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
                # Lấy tất cả file hỗ trợ
                exts = ["*.txt", "*.html", "*.epub", "*.docx", "*.md"]
                files = []
                for ext in exts:
                    files.extend(list(full_dir.glob(ext)))
                    
                for txt_file in files:
                    novel_id = txt_file.stem
                    novel_split_dir = split_dir / novel_id
                    if not novel_split_dir.exists():
                        logger.info(f"[Daemon Raw] Đang băm chương truyện: {novel_id}")
                        source_mgr.split_and_init_novel(novel_id, txt_file.name)
                        # Đã xử lý xong, move file
                        import shutil
                        shutil.move(str(txt_file), str(processed_dir / txt_file.name))
        except Exception as e:
            logger.info(f"[Daemon Raw] Lỗi: {e}")
        time.sleep(300)

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
                            logger.info(f"[Daemon Init] Đang khởi tạo dự án: {novel_id}")
                            pm = PipelineManager(novel_id, str(split_dir / novel_id), str(out_dir / novel_id))
                            pm.init_new_novel()
        except Exception as e:
            logger.info(f"[Daemon Init] Lỗi: {e}")
        time.sleep(300)

def daemon_pipeline_executor():
    """Mỗi 2 phút: Kiểm tra các Pipeline đang chạy, dispatch max 4 branch song song."""
    from concurrent.futures import ThreadPoolExecutor
    executor = ThreadPoolExecutor(max_workers=4)
    
    while True:
        try:
            if not load_settings().get("daemon_pipeline", True):
                time.sleep(30)
                continue
                
            out_dir = engine_dir / "Output"
            tasks = []
            if out_dir.exists():
                for pdir in out_dir.iterdir():
                    if pdir.is_dir() and (pdir / "State" / "toc.json").exists():
                        novel_id = pdir.name
                        with open(pdir / "State" / "toc.json", 'r', encoding='utf-8') as f:
                            toc = json.load(f)
                        
                        pending_chaps = [c.get('file', c.get('name', '')) for c in toc.get('chapters', []) if c.get('status') == 'pending']
                        done_chaps = sum(1 for c in toc.get('chapters', []) if c.get('status') == 'done')
                        total_chaps = len(toc.get('chapters', []))
                        
                        # Cập nhật Pinned Message
                        if total_chaps > 0:
                            status_msg = f"✅ Đã dịch: {done_chaps}/{total_chaps} ({int(done_chaps/total_chaps*100)}%)\n⏳ Đang xử lý: {min(len(pending_chaps), 4)} luồng"
                            update_pinned_progress(novel_id, status_msg)
                        
                        for chap in pending_chaps[:4]: # Max 4 from each project
                            tasks.append((novel_id, chap))
            
            # Dispatch max 4 tasks globally
            def process_task(args):
                nid, cname = args
                logger.info(f"[Daemon Pipeline] Bắt đầu dịch: {nid} - {cname}")
                pm = PipelineManager(nid, str(engine_dir / "Source_Split" / nid), str(engine_dir / "Output" / nid))
                import lock_mgr
                with lock_mgr.file_lock:
                    toc_path = engine_dir / "Output" / nid / "State" / "toc.json"
                    with open(toc_path, 'r', encoding='utf-8') as f: toc = json.load(f)
                    for c in toc.get('chapters', []):
                        if c.get('file', c.get('name')) == cname: c['status'] = 'processing'
                    with open(toc_path, 'w', encoding='utf-8') as f: json.dump(toc, f, ensure_ascii=False, indent=4)
                
                success, err = pm.process_chapter(cname)
                
                # Update status back
                with lock_mgr.file_lock:
                    with open(toc_path, 'r', encoding='utf-8') as f: toc = json.load(f)
                    for c in toc.get('chapters', []):
                        if c.get('file', c.get('name')) == cname:
                            c['status'] = 'done' if success else 'pending'
                            c['error'] = err if not success else ''
                    with open(toc_path, 'w', encoding='utf-8') as f: json.dump(toc, f, ensure_ascii=False, indent=4)
                
                if not success:
                    update_pinned_progress(nid, f"❌ Lỗi tại `{cname}`:\n{err[:200]}...")
            
            for t in tasks[:4]:
                executor.submit(process_task, t)
                
        except Exception as e:
            logger.info(f"[Daemon Pipeline] Lỗi: {e}")
        time.sleep(120)

# Khởi động Daemons
threading.Thread(target=daemon_raw_processing, daemon=True).start()
threading.Thread(target=daemon_project_init, daemon=True).start()
threading.Thread(target=daemon_pipeline_executor, daemon=True).start()
