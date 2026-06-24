import json
import sqlite3
import re
from pathlib import Path
import sys
from pathlib import Path
import os

def _atomic_write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

# Thêm đường dẫn để import lock_mgr
engine_dir = Path(__file__).parent
sys.path.append(str(engine_dir))
import lock_mgr

CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')


def _chapter_index_from_filename(chapter_filename: str):
    match = re.search(r'(?:Chapter|Chương)\s*0*([0-9]+)', chapter_filename, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _safe_filename_part(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', '', text or '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:120]


def _strip_chapter_prefix(title: str) -> str:
    title = re.sub(r'^\s*#+\s*', '', title or '').strip()
    title = re.sub(r'^\s*(?:Chương|Chapter)\s*[0-9０-９一二三四五六七八九十百千万萬零〇两兩]+\s*[:：.\-、]?\s*', '', title, flags=re.IGNORECASE)
    return title.strip()


def _normalize_final_title(final_text: str, chapter_index: int | None):
    lines = final_text.splitlines()
    first_line = lines[0].strip() if lines else ""
    title = _strip_chapter_prefix(first_line) if first_line.startswith("#") else ""
    if title and CJK_RE.search(title):
        title = ""

    if chapter_index is None:
        return final_text, _safe_filename_part(title) or "chapter"

    heading = f"Chương {chapter_index:04d}" + (f" {title}" if title else "")
    if lines and first_line.startswith("#"):
        lines[0] = f"# {heading}"
        final_text = "\n".join(lines)
    else:
        final_text = f"# {heading}\n\n{final_text}".strip() + "\n"
    return final_text, heading


def _assert_no_cjk(final_text: str):
    hits = []
    for line_no, line in enumerate(final_text.splitlines(), 1):
        if CJK_RE.search(line):
            hits.append(f"L{line_no}: {line[:120]}")
            if len(hits) >= 5:
                break
    if hits:
        raise ValueError("Final còn sót CJK, chặn ghi file: " + " | ".join(hits))

def run(novel_id: str, out_dir: Path, chapter_filename: str, ai_output: dict, context_pack: dict = None):
    """BƯỚC 4: Hậu Xử Lý
    - Tách ghép output trả bản dịch (_vi.md)
    - Cập nhật Character, Glossary, Grammar rules vào Database
    - Cập nhật Story Timeline
    - Cập nhật README, TOC
    """
    print(f"[Stage 4] Đang hậu xử lý cho: {chapter_filename}")
    
    errors = []
    
    # --- 4a. Ghi file dịch ---
    try:
        if 'refined_segments' in ai_output:
            final_text = "\n\n".join([seg.get('refined_translation', '') if isinstance(seg, dict) else str(seg) for seg in ai_output.get('refined_segments', [])])
        elif 'translated_content' in ai_output:
            final_text = ai_output['translated_content']
        else:
            final_text = "\n\n".join([str(seg) for seg in ai_output.get('refined_segments', [])])
            
        state_dir = out_dir / "State"
        final_dir = out_dir / "Final_Translated"
        
        toc_file = state_dir / "toc.json"
        old_translated_file = ""
        chapter_index = _chapter_index_from_filename(chapter_filename)
        if toc_file.exists():
            try:
                with open(toc_file, 'r', encoding='utf-8') as f:
                    current_toc = json.load(f)
                for idx, row in enumerate(current_toc.get("chapters", []), 1):
                    if row.get('file', row.get('name')) == chapter_filename:
                        chapter_index = row.get('index') if isinstance(row.get('index'), int) else chapter_index or idx
                        old_translated_file = row.get('translated_file') or ""
                        break
            except Exception:
                pass

        final_text, final_title = _normalize_final_title(final_text, chapter_index)
        _assert_no_cjk(final_text)
        final_filename = f"{_safe_filename_part(final_title)}.md"
            
        # Xóa file cũ (tránh duplicate)
        prefixes = []
        m = re.match(r'^(Chapter \d+)', chapter_filename, re.IGNORECASE)
        if m:
            prefixes.append(m.group(1))
        if chapter_index is not None:
            prefixes.extend([f"Chương {chapter_index}", f"Chương {chapter_index:04d}"])
        for prefix in prefixes:
            for old_file in final_dir.glob(f"{prefix}*.md"):
                if old_file.name != final_filename:
                    try: old_file.unlink()
                    except: pass
        if old_translated_file and old_translated_file != final_filename:
            try:
                (final_dir / old_translated_file).unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        
        out_chap_path = final_dir / final_filename
        if out_chap_path.exists():
            try: out_chap_path.unlink()
            except: pass

        with open(out_chap_path, 'w', encoding='utf-8') as f:
            f.write(final_text)
    except Exception as e:
        errors.append(f"[4a Assemble] {e}")
        final_filename = chapter_filename.replace(".md", "_vi.md")

    # --- 4b. Cập nhật Database (Knowledge Extractor, TM, Relationships) ---
    try:
        from knowledge_extractor import KnowledgeExtractor
        from tm_lookup import TMEngine
        from relationship_manager import RelationshipManager
        
        with lock_mgr.file_lock:
            # 1. Trích xuất ứng viên từ điển
            extractor = KnowledgeExtractor(novel_id)
            extractor.process_new_entities(ai_output.get('new_entities', []))
            
            # 2. Cập nhật Relationship Graph
            rel_mgr = RelationshipManager(novel_id)
            rel_mgr.save_relationships(ai_output.get('relationships', []))
            
            # 3. Lưu lại bản dịch vào Translation Memory
            tm_engine = TMEngine()
            if context_pack and 'raw_segments' in context_pack:
                raw_segments = context_pack['raw_segments']
                ai_segments = ai_output.get('refined_segments', [])
                
                # Tạo map từ id -> raw_text
                raw_map = {seg['id']: seg['text'] for seg in raw_segments if isinstance(seg, dict) and 'id' in seg and 'text' in seg}
                
                # Lưu vào TM
                for seg in ai_segments:
                    if not isinstance(seg, dict): continue
                    sid = seg.get('id')
                    translated = seg.get('refined_translation', '')
                    if sid in raw_map and translated:
                        raw_text = raw_map[sid]
                        # Không lưu nếu câu quá ngắn
                        if len(raw_text) > 5:
                            tm_engine.save(raw_text, translated, project_scope=novel_id)
            
    except Exception as e:
        errors.append(f"[4b Dict DB] {e}")

    # --- 4c. Ghi file Character / Glossary ---
    try:
        with lock_mgr.file_lock:
            new_chars = [e for e in ai_output.get('new_entities', []) if isinstance(e, dict) and e.get('type') == 'character']
            new_gloss = [e for e in ai_output.get('new_entities', []) if isinstance(e, dict) and e.get('type') != 'character']
            
            char_json = state_dir / "new_characters.json"
            chars = []
            if char_json.exists():
                try:
                    with open(char_json, 'r', encoding='utf-8') as f: chars = json.load(f)
                    chars = [c for c in chars if isinstance(c, dict)] # Lọc rác từ lần chạy lỗi trước
                except: pass
            chars.extend(new_chars)
            with open(char_json, 'w', encoding='utf-8') as f: json.dump(chars, f, ensure_ascii=False, indent=2)
                
            gloss_json = state_dir / "new_glossary.json"
            gloss = []
            if gloss_json.exists():
                try:
                    with open(gloss_json, 'r', encoding='utf-8') as f: gloss = json.load(f)
                    gloss = [g for g in gloss if isinstance(g, dict)] # Lọc rác
                except: pass
            gloss.extend(new_gloss)
            with open(gloss_json, 'w', encoding='utf-8') as f: json.dump(gloss, f, ensure_ascii=False, indent=2)
            
            char_md = state_dir / "Character.md"
            with open(char_md, 'w', encoding='utf-8') as f:
                f.write("# Character Dictionary\n\n")
                for c in chars:
                    f.write(f"- **{c.get('raw', '')}** -> {c.get('target', '')}\n")
                    
            gloss_md = state_dir / "Glossary.md"
            with open(gloss_md, 'w', encoding='utf-8') as f:
                f.write("# Term Glossary\n\n")
                for g in gloss:
                    f.write(f"- **{g.get('raw', '')}** ({g.get('type', '')}) -> {g.get('target', '')}\n")
    except Exception as e:
        errors.append(f"[4c Entity Files] {e}")

    # --- 4d. Cập nhật Timeline, TOC, README ---
    try:
        with lock_mgr.file_lock:
            toc_file = state_dir / "toc.json"
            readme_file = out_dir / "README.md"
            toc = {}
            chapters = []
            chapter_index = None

            if toc_file.exists():
                with open(toc_file, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                chapters = toc.get('chapters', []) if isinstance(toc.get('chapters', []), list) else []

            for idx, ch in enumerate(chapters, 1):
                if not isinstance(ch, dict):
                    continue
                if not isinstance(ch.get('index'), int):
                    ch['index'] = idx
                if ch.get('file', ch.get('name')) == chapter_filename:
                    chapter_index = ch['index']
                    ch['status'] = 'done'
                    ch['translated_file'] = final_filename
                    ch['error'] = ''
                    ch.pop('processing_started_at', None)

            if chapter_index is None:
                match = re.search(r'(?:Chapter|Chương)\s*0*([0-9]+)', chapter_filename, re.IGNORECASE)
                chapter_index = int(match.group(1)) if match else None

            timeline_file = state_dir / "story_timeline.json"
            timeline = []
            if timeline_file.exists():
                try:
                    with open(timeline_file, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                    timeline = loaded if isinstance(loaded, list) else []
                except Exception:
                    timeline = []
            timeline = [ev for ev in timeline if isinstance(ev, dict)]

            ai_timeline = ai_output.get('story_timeline', {})
            if isinstance(ai_timeline, dict):
                summary = ai_timeline.get('summary', {})
                if not isinstance(summary, dict):
                    summary = {"main_events": str(summary), "new_characters": []}
                timeline = [
                    ev for ev in timeline
                    if ev.get('chapter_file') != chapter_filename and ev.get('chapter') != final_filename
                ]
                timeline.append({
                    "chapter_index": chapter_index,
                    "chapter_file": chapter_filename,
                    "translated_file": final_filename,
                    "chapter": final_filename,
                    "summary": summary,
                })

            timeline.sort(key=lambda ev: (
                ev.get('chapter_index') if isinstance(ev.get('chapter_index'), int) else 10**9,
                ev.get('chapter_file') or ev.get('chapter') or '',
            ))
            with open(timeline_file, 'w', encoding='utf-8') as f:
                json.dump(timeline, f, ensure_ascii=False, indent=2)

            timeline_md = state_dir / "story-timeline.md"
            with open(timeline_md, 'w', encoding='utf-8') as f:
                f.write("# Story Timeline\n\n")
                for ev in timeline:
                    chap = ev.get('translated_file') or ev.get('chapter') or ev.get('chapter_file') or ''
                    idx = ev.get('chapter_index')
                    heading = f"Chương {idx}: {chap}" if isinstance(idx, int) else chap
                    sm = ev.get('summary', {})
                    if not isinstance(sm, dict):
                        sm = {}
                    f.write(f"## {heading}\n")
                    f.write(f"- **Sự kiện chính:** {sm.get('main_events', '')}\n")
                    new_c = sm.get('new_characters', [])
                    if new_c and isinstance(new_c, list):
                        f.write(f"- **Nhân vật mới xuất hiện:** {', '.join(str(x) for x in new_c)}\n")
                    f.write("\n")

            if toc_file.exists():
                total = len(chapters)
                done = sum(1 for ch in chapters if isinstance(ch, dict) and ch.get('status') == 'done')
                _atomic_write_json(toc_file, toc)

                if readme_file.exists():
                    with open(readme_file, 'r', encoding='utf-8') as f:
                        readme = f.read()
                    readme = re.sub(r'\*\*Tiến độ:\*\* \d+ / \d+', f'**Tiến độ:** {done} / {total}', readme)
                    with open(readme_file, 'w', encoding='utf-8') as f:
                        f.write(readme)
    except Exception as e:
        errors.append(f"[4d TOC/Timeline] {e}")

    if errors:
        raise ValueError("[Stage 4 FAILED] " + "; ".join(errors))
        
    print("✅ [Stage 4 PASS] Hậu xử lý thành công, mọi file đã được cập nhật.")
    return True
