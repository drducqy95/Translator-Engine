import os
import json
from pathlib import Path
from qt_engine import QTEngine
from chapter_parser import ChapterParser
from preprocessor import preprocess_text

def test_chapter():
    chap_file = Path("/sdcard/My Agent/Translator Engine/Test/Chapter 0008 喜大普奔，恭喜无限游戏正式开服！.md")
    out_file = Path("/sdcard/My Agent/Translator Engine/Test/Chapter 0008_draft.json")
    
    print("Khởi tạo QT Engine...")
    qt = QTEngine()
    
    raw_text = preprocess_text(chap_file.read_text(encoding='utf-8'))
    parser = ChapterParser(raw_text)
    chapters = parser.split_to_chapters()
    
    # Kích hoạt Context (Universes) dựa trên nội dung text
    qt.set_context(raw_text)
    
    total_coverage = 0.0
    seg_count = 0
    unknowns_counter = {}
    
    chapters_data = []
    
    for heading, body in chapters:
        chapter_data = {
            "chapter_heading_raw": heading,
            "chapter_heading_draft": qt.translate(heading)[0] if heading else "",
            "segments": []
        }
        
        segments = ChapterParser.segment_chapter(body)
        for idx, seg in enumerate(segments):
            draft, cov, unk = qt.translate(seg)
            chapter_data["segments"].append({
                "id": idx + 1,
                "raw": seg,
                "draft": draft
            })
            total_coverage += cov
            seg_count += 1
            for u in unk:
                raw_u = u['raw']
                tgt_u = u['target']
                if raw_u not in unknowns_counter:
                    unknowns_counter[raw_u] = {"target": tgt_u, "frequency": 0}
                if 'foreign_context' in u and 'foreign_context' not in unknowns_counter[raw_u]:
                    unknowns_counter[raw_u]['foreign_context'] = u['foreign_context']
                unknowns_counter[raw_u]["frequency"] += 1
            
        chapters_data.append(chapter_data)

    avg_cov = total_coverage / seg_count if seg_count > 0 else 0
    
    # Chuẩn bị danh sách Entities
    entities_list = []
    for raw_u, meta in unknowns_counter.items():
        ent = {
            "raw": raw_u,
            "target": meta["target"],
            "frequency": meta["frequency"]
        }
        if "foreign_context" in meta:
            ent["foreign_context"] = meta["foreign_context"]
        entities_list.append(ent)
        
    entities_list.sort(key=lambda x: x["frequency"], reverse=True)
    
    final_output = {
        "chapters": chapters_data,
        "entities": entities_list
    }
    
    # Ghi ra JSON
    out_file.write_text(json.dumps(final_output, ensure_ascii=False, indent=2), encoding='utf-8')
    
    print(f"\n✅ Đã dịch xong. Kết quả lưu tại: {out_file.name}")
    print(f"📊 Số segment đã dịch: {seg_count}")
    print(f"📊 Độ bao phủ trung bình (Coverage): {avg_cov:.2%}")
    print(f"❓ Số lượng Entities (Unknown): {len(entities_list)}")
    if entities_list:
        print(f"   Top 5 Entities: {entities_list[:5]}")
        
    qt.close()

if __name__ == '__main__':
    test_chapter()
