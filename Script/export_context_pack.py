import json
import re
from pathlib import Path
from qt_engine import QTEngine

def main():
    print("Khởi tạo QT Engine...")
    qt = QTEngine()
    
    test_file = Path("/sdcard/My Agent/Translator Engine/Test/Chapter 0008 喜大普奔，恭喜无限游戏正式开服！.md")
    
    with open(test_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Tách segment
    paragraphs = [p for p in content.split('\n') if p.strip()]
    
    draft_segments = []
    
    # Tracking
    all_known_characters = {}
    all_known_glossary = {}
    all_unknown_entities = {}
    
    print("Bắt đầu dịch và phân tích...")
    qt.set_context(content)
    for idx, raw in enumerate(paragraphs, 1):
        draft, cov, unknown, known = qt.translate(raw)
        
        draft_segments.append({
            "id": idx,
            "raw": raw,
            "draft": draft
        })
        
        # Gom nhóm known entities
        for ent in known:
            k = ent['raw']
            target = ent['target']
            etype = ent['type']
            
            if etype in ('character', 'name'):
                if k not in all_known_characters:
                    all_known_characters[k] = {"raw": k, "target": target, "type": etype, "frequency": 0}
                all_known_characters[k]["frequency"] += 1
            elif etype in ('sect', 'location', 'item', 'entity', 'universe'):
                if k not in all_known_glossary:
                    all_known_glossary[k] = {"raw": k, "target": target, "type": etype, "frequency": 0}
                all_known_glossary[k]["frequency"] += 1
                
        # Gom nhóm unknown entities
        for ent in unknown:
            k = ent['raw']
            if k not in all_unknown_entities:
                all_unknown_entities[k] = ent
                all_unknown_entities[k]["frequency"] = 0
            all_unknown_entities[k]["frequency"] += 1

    # Phân loại unknown entities vào character hoặc glossary tùy vào việc AI có thể đoán từ foreign_context không
    # Ở đây cứ tống hết vào character_candidates để AI tự phân xử
    characters = list(all_known_characters.values())
    for u in all_unknown_entities.values():
        characters.append({
            "raw": u["raw"],
            "target": u["target"],
            "type": "unknown_entity",
            "foreign_context": u.get("foreign_context"),
            "frequency": u["frequency"]
        })
        
    glossary = list(all_known_glossary.values())

    context_pack = {
        "translation_config": {
            "style": "Đô thị / Võng Du",
            "tone": "Lưu loát, văn phong game thủ hiện đại",
            "instruction": "1. Dịch chuẩn xác thuật ngữ game. 2. Giữ nguyên tên nhân vật nước ngoài. 3. Phân tích ngữ pháp và trích xuất dữ liệu trả về ĐÚNG CẤU TRÚC JSON.",
            "expected_ai_schema": {
                "refined_segments": [
                    {"id": 1, "refined_translation": "..."}
                ],
                "new_entities": [
                    {"raw": "...", "target": "...", "type": "character|sect|location|item|martial_art"}
                ],
                "grammar_rules": [
                    {
                        "pattern": "Cấu trúc regex hoặc chuỗi cần tìm (VD: (.*)的(.*))",
                        "replacement": "Cấu trúc thay thế (VD: \\2 của \\1)",
                        "condition": "Điều kiện từ loại (VD: n de n)",
                        "description": "Mô tả luật ngữ pháp để nạp vào DB"
                    }
                ],
                "chapter_summary": {
                    "main_events": "Tóm tắt sự kiện chính trong chương",
                    "new_characters": ["Các nhân vật mới xuất hiện"],
                    "relationships_updated": ["Mối quan hệ mới/thay đổi"],
                    "new_terms": ["Thuật ngữ mới"],
                    "new_weapons_items": ["Vũ khí, trang bị mới"],
                    "new_martial_arts": ["Công pháp, kỹ năng mới"]
                }
            }
        },
        "chapter_info": {
            "title_raw": paragraphs[1] if len(paragraphs) > 1 else "",
            "title_draft": draft_segments[1]["draft"] if len(draft_segments) > 1 else ""
        },
        "story_timeline": "Chương 1-7: Cơ Thành là một game thủ bình thường. Một trò chơi có tên là 'Vô Hạn Trò Chơi' sắp ra mắt...",
        "characters": characters,
        "glossary": glossary,
        "draft_segments": draft_segments
    }
    
    output_path = Path("/sdcard/My Agent/Translator Engine/Test/context_pack.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(context_pack, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Đã tạo Context Pack thành công: {output_path}")
    print(f"📊 Số segments: {len(draft_segments)}")
    print(f"👤 Số Characters (Bao gồm Unknown): {len(characters)}")
    print(f"📚 Số Glossary: {len(glossary)}")

if __name__ == '__main__':
    main()
