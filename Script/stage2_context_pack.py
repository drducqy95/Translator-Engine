import json
import sqlite3
import re
from pathlib import Path
from tm_lookup import TMEngine


DEFAULT_TRANSLATION_CONFIG = {
    "translation_goal": {
        "style": "văn xuôi tiếng Việt tự nhiên, chính xác nghĩa, giữ giọng truyện",
        "anti_goals": [
            "Không giữ ký tự CJK trong bản dịch cuối",
            "Không đổi target đã khóa trong Locked Dictionary",
            "Không dịch lại tên Latin sang Hán Việt",
        ],
    }
}


def _collect_present_terms(chapter_content: str, mapping: dict) -> dict:
    if not isinstance(mapping, dict):
        return {}
    text = chapter_content or ""
    return {k: v for k, v in mapping.items() if k and k in text}


def _filter_locked_dictionary(chapter_content: str, locked_dict: dict) -> dict:
    if not isinstance(locked_dict, dict):
        return {"characters": {}, "glossary": {}}
    result = {"characters": {}, "glossary": {}}
    characters = locked_dict.get("characters", {})
    glossary = locked_dict.get("glossary", {})
    if isinstance(characters, dict):
        result["characters"] = _collect_present_terms(chapter_content, characters)
    if isinstance(glossary, dict):
        result["glossary"] = _collect_present_terms(chapter_content, glossary)
    return result

def _chapter_index_from_name(name: str):
    match = re.search(r"(?:Chapter|Chương)\s*0*([0-9]+)", name or "", re.IGNORECASE)
    return int(match.group(1)) if match else None

def run(novel_id: str, chapter_content: str, stage1_data: dict, output_dir: str, chapter_filename: str = ""):
    """BƯỚC 2: Tạo Context Pack
    - Đóng gói Raw Content
    - Tổng hợp Translation Config
    - Lấy thông tin Entity và Xưng hô từ Stage 1
    - Truy xuất các Entity đã khóa từ Database (Project DB)
    """
    print(f"[Stage 2] Đang tạo Context Pack cho truyện {novel_id}")
    out_path = Path(output_dir)
    
    engine_root = Path(__file__).parent.parent

    # 1. Translation Config
    translator_config = {}
    config_path = out_path / "State" / "translation_config.json"
    if not config_path.exists():
        config_path = engine_root / "Temp" / "translation_config.json"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            translator_config = json.load(f)
    if not translator_config:
        translator_config = DEFAULT_TRANSLATION_CONFIG.copy()
        print("[Stage 2] Không tìm thấy translation_config.json; dùng default config an toàn.")
            
    # 2. Timeline
    timeline_file = out_path / "State" / "story_timeline.json"
    timeline = []
    if timeline_file.exists():
        try:
            with open(timeline_file, 'r', encoding='utf-8') as f:
                timeline = json.load(f)
        except: pass
        
    # 3. Project DB Locked Terms
    locked_dict = {
        "characters": {},
        "glossary": {}
    }
    db_path = engine_root / "Dict" / f"project_{novel_id}.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT key, target, type FROM dict_entries")
            for row in cursor.fetchall():
                key, target, ent_type = row
                if ent_type == 'character':
                    locked_dict['characters'][key] = target
                else:
                    locked_dict['glossary'][key] = f"{target} ({ent_type})"
            conn.close()
        except Exception as e:
            print(f"[Stage 2] Lỗi đọc Database: {e}")

    locked_dict = _filter_locked_dictionary(chapter_content, locked_dict)
            
    # 4. Lưu Stage 1 new entities thành suggested_dictionary (to assist AI)
    # The AI in Stage 3 should know these are just suggestions, not strict locks.
    suggested_dict = {
        "characters": stage1_data.get('characters', {}),
        "glossary": stage1_data.get('glossary', {})
    }
    
    # 4.5 Relationship Graph
    try:
        from relationship_manager import RelationshipManager
        rel_mgr = RelationshipManager(novel_id)
        relationships = rel_mgr.get_context()
    except Exception:
        relationships = []

    # 5. Extract Pronouns
    pronouns = stage1_data.get('pronouns', {})

    from qt_engine import QTEngine, format_draft
    qt = QTEngine()
    qt.set_context(chapter_content)
    # 6. Break Raw Content into Segments & TM Lookup
    tm_engine = TMEngine()
    raw_segments = []
    tm_hits = []
    for i, p in enumerate(chapter_content.split('\n')):
        p = p.strip()
        if not p: continue
        draft_text, _, _, _ = qt.translate(p, project_scope=novel_id)
        raw_segments.append({"id": i+1, "text": p, "qt": format_draft(draft_text)})
        tm_res = tm_engine.lookup(p, project_scope=novel_id)
        if tm_res:
            tm_hits.append({"raw": p, "translated": tm_res})

    current_index = _chapter_index_from_name(chapter_filename)
    if not isinstance(timeline, list):
        timeline = []
    timeline = [ev for ev in timeline if isinstance(ev, dict)]
    timeline.sort(key=lambda ev: (ev.get("chapter_index") if isinstance(ev.get("chapter_index"), int) else 10**9, ev.get("chapter_file") or ev.get("chapter") or ""))
    if current_index is not None:
        timeline = [ev for ev in timeline if not isinstance(ev.get("chapter_index"), int) or ev.get("chapter_index") < current_index]
    recent_timeline = timeline[-5:]

    # Build the massive Context Pack
    context_pack = {
        "translation_config": translator_config,
        "current_chapter": {"file": chapter_filename, "index": current_index},
        "story_timeline": recent_timeline,
        "locked_dictionary": locked_dict,
        "suggested_dictionary": suggested_dict,
        "relationships_graph": relationships,
        "pronouns_addressing": pronouns,
        "translation_memory_hits": tm_hits,
        "raw_segments": raw_segments
    }
    
    # PipelineManager ghi context pack vào Intermediate/<chapter>/pre-trans.
    
    if not context_pack.get("translation_config"):
        raise ValueError("[Stage 2 FAILED] Context Pack thiếu config.")
        
    print("✅ [Stage 2 PASS] Đã tạo xong Context Pack bao gồm Xưng Hô (Pronouns).")
    return context_pack
