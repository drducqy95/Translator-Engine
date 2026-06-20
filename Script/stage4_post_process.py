import json
import sqlite3
import re
from pathlib import Path
import sys
from pathlib import Path

# Thêm đường dẫn để import lock_mgr
engine_dir = Path(__file__).parent
sys.path.append(str(engine_dir))
import lock_mgr

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
        
        # Lấy tiêu đề từ dòng đầu tiên để đặt tên file
        first_line = final_text.split('\n')[0].strip() if final_text else ""
        if first_line.startswith('# '):
            title = first_line.replace('# ', '')
            title = re.sub(r'[\\/:*?"<>|]', '', title)
            final_filename = f"{title}.md"
        else:
            final_filename = chapter_filename.replace(".md", "_vi.md")
            
        out_chap_path = final_dir / final_filename
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
            timeline_file = state_dir / "story_timeline.json"
            timeline = []
            if timeline_file.exists():
                try: 
                    with open(timeline_file, 'r', encoding='utf-8') as f: timeline = json.load(f)
                except: pass
                    
            ai_timeline = ai_output.get('story_timeline', {})
            if isinstance(ai_timeline, dict):
                timeline.append({
                    "chapter": final_filename,
                    "summary": ai_timeline.get('summary', {})
                })
            with open(timeline_file, 'w', encoding='utf-8') as f:
                json.dump(timeline, f, ensure_ascii=False, indent=2)
                
            timeline_md = state_dir / "story-timeline.md"
            with open(timeline_md, 'w', encoding='utf-8') as f:
                f.write("# Story Timeline\n\n")
                for ev in timeline:
                    if not isinstance(ev, dict): continue
                    chap = ev.get('chapter', '')
                    sm = ev.get('summary', {})
                    if not isinstance(sm, dict): sm = {}
                    f.write(f"## {chap}\n")
                    f.write(f"- **Sự kiện chính:** {sm.get('main_events', '')}\n")
                    new_c = sm.get('new_characters', [])
                    if new_c and isinstance(new_c, list):
                        f.write(f"- **Nhân vật mới xuất hiện:** {', '.join(str(x) for x in new_c)}\n")
                    f.write("\n")
                
            toc_file = state_dir / "toc.json"
            readme_file = out_dir / "README.md"
            if toc_file.exists():
                with open(toc_file, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                total = len(toc.get('chapters', []))
                done = 0
                for ch in toc.get('chapters', []):
                    if ch.get('file', ch.get('name')) == chapter_filename:
                        ch['status'] = 'done'
                        ch['translated_file'] = final_filename
                    if ch.get('status') == 'done':
                        done += 1
                with open(toc_file, 'w', encoding='utf-8') as f:
                    json.dump(toc, f, ensure_ascii=False, indent=2)
                    
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
