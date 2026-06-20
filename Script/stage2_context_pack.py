import json
import sqlite3
from pathlib import Path
from tm_lookup import TMEngine

def run(novel_id: str, chapter_content: str, stage1_data: dict, output_dir: str):
    """BƯỚC 2: Tạo Context Pack
    - Đóng gói Raw Content
    - Tổng hợp Translation Config
    - Lấy thông tin Entity và Xưng hô từ Stage 1
    - Truy xuất các Entity đã khóa từ Database (Project DB)
    """
    print(f"[Stage 2] Đang tạo Context Pack cho truyện {novel_id}")
    out_path = Path(output_dir)
    
    # 1. Translation Config
    translator_config = {}
    config_path = out_path / "translation_config.json"
    if not config_path.exists():
        config_path = Path("/sdcard/My Agent/Translator Engine/Temp/translation_config.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            translator_config = json.load(f)
            
    # 2. Timeline
    timeline_file = out_path / "story_timeline.json"
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
    db_path = Path("/sdcard/My Agent/Translator Engine/Dict") / f"project_{novel_id}.db"
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

    # 6. Break Raw Content into Segments & TM Lookup
    tm_engine = TMEngine()
    raw_segments = []
    tm_hits = []
    for i, p in enumerate(chapter_content.split('\n')):
        p = p.strip()
        if not p: continue
        raw_segments.append({"id": i+1, "text": p})
        tm_res = tm_engine.lookup(p, project_scope=novel_id)
        if tm_res:
            tm_hits.append({"raw": p, "translated": tm_res})

    # Build the massive Context Pack
    context_pack = {
        "translation_config": translator_config,
        "story_timeline": timeline[-5:],  # Lấy 5 sự kiện gần nhất
        "locked_dictionary": locked_dict,
        "suggested_dictionary": suggested_dict,
        "relationships_graph": relationships,
        "pronouns_addressing": pronouns,
        "translation_memory_hits": tm_hits,
        "raw_segments": raw_segments
    }
    
    # Ghi file context pack ra để user có thể xem định dạng
    with open(out_path / "context_pack.json", 'w', encoding='utf-8') as f:
        json.dump(context_pack, f, ensure_ascii=False, indent=2)
    
    if not context_pack.get("translation_config"):
        raise ValueError("[Stage 2 FAILED] Context Pack thiếu config.")
        
    print("✅ [Stage 2 PASS] Đã tạo xong Context Pack bao gồm Xưng Hô (Pronouns).")
    return context_pack
