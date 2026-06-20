import json
from pathlib import Path

def build_stage3_prompt(context_pack):
    config = context_pack.get("translation_config", {})
    goal = config.get("translation_goal", {})
    style = goal.get("style", "văn xuôi tiếng Việt mượt, rõ nghĩa, không máy móc")
    anti_goals = goal.get("anti_goals", [])
    
    # Build dynamic prompt
    prompt = f"""Bạn là một Bậc thầy Dịch thuật Văn học (Tiếng Trung -> Tiếng Việt).
Nhiệm vụ của bạn là dịch chương truyện dựa trên một Gói Ngữ Cảnh (Context Pack) được cung cấp.

MỤC TIÊU DỊCH THUẬT:
- Phong cách: {style}
- Những điều tuyệt đối TRÁNH:
"""
    for anti in anti_goals:
        prompt += f"  - {anti}\n"
        
    prompt += """
LUẬT LỆ ÉP BUỘC (CRITICAL):
1. BÁM SÁT TỪ ĐIỂN CUNG CẤP TRONG CONTEXT PACK: Bất kỳ tên nhân vật, địa danh, chiêu thức nào xuất hiện trong phần 'Locked Dictionary' của Context Pack ĐỀU PHẢI được dùng đúng như vậy. Cấm tự ý thay đổi tên nhân vật đã khóa.
2. XƯNG HÔ (PRONOUNS): Bắt buộc phải tuân theo hệ thống xưng hô trong phần 'Pronouns & Addressing'.
3. ĐỊNH DẠNG (BẮT BUỘC): Bạn phải dịch từng đoạn (segment) một, giữ nguyên số lượng và ID của các đoạn. Tuyệt đối không gộp đoạn hay tách đoạn.
4. TIÊU ĐỀ CHƯƠNG: Đoạn đầu tiên (thường có id=1) BẮT BUỘC phải là tiêu đề chương đã được dịch sang tiếng Việt, giữ nguyên định dạng Markdown heading (ví dụ: # Chương 1: Tên chương).
5. SUGGESTED DICTIONARY & TÊN RIÊNG MỚI (NEW ENTITIES): Phần 'Suggested Dictionary' là các gợi ý từ máy dịch (QT), KHÔNG BẮT BUỘC. Nếu phát hiện tên riêng (character, place) CHƯA CÓ trong Locked Dictionary, bạn BẮT BUỘC phải sử dụng Âm Hán Việt chuẩn, tuyệt đối KHÔNG dịch nghĩa đen, KHÔNG bám theo Suggested Dictionary nếu nó dịch nghĩa đen sai lệch (Ví dụ: "赵奇" phải dịch là "Triệu Kỳ", tuyệt đối không dịch là "Triệu Đơn").
6. TRẢ VỀ DUY NHẤT JSON: Đầu ra của bạn phải là một chuỗi JSON hợp lệ, tuyệt đối không có text dư thừa, không có ```json markdown.

ĐỊNH DẠNG JSON ĐẦU RA YÊU CẦU:
{
  "refined_segments": [
    {
      "id": 1,
      "refined_translation": "# Chương 1: Tiêu đề chương"
    },
    {
      "id": 2,
      "refined_translation": "Nội dung bản dịch của đoạn 2..."
    }
  ],
  "story_timeline": {
    "summary": {
      "main_events": "Tóm tắt ngắn gọn 1-2 câu về sự kiện chính xảy ra trong chương này",
      "new_characters": ["Tên nhân vật mới 1", "Tên nhân vật mới 2"]
    }
  },
  "new_entities": [
    {
      "raw": "Tên/Thuật ngữ gốc tiếng Trung",
      "target": "Tên/Thuật ngữ dịch sang tiếng Việt (chuẩn Hán Việt)",
      "type": "character",
      "origin": "chinese",
      "name_type": "person"
    }
  ],
  "relationships": [
    {
      "source": "Tên nhân vật A",
      "target": "Tên nhân vật B",
      "relationship": "Mối quan hệ (ví dụ: master_of, enemy_of, spouse_of)"
    }
  ]
}
"""
    return prompt

def run(novel_id: str, context_pack: dict, output_dir: str):
    print(f"[Stage 3] Khởi tạo AI Refiner (Translator) cho truyện {novel_id}")
    
    system_prompt = build_stage3_prompt(context_pack)
    raw_segments = context_pack.get("raw_segments", [])
    raw_text = "\n".join([f"[{s['id']}] {s['text']}" for s in raw_segments])
    dict_locked = context_pack.get("locked_dictionary", {})
    dict_suggest = context_pack.get("suggested_dictionary", {})
    pronouns = context_pack.get("pronouns_addressing", {})
    
    user_prompt = f"""
=== LOCKED DICTIONARY (BẮT BUỘC) ===
{json.dumps(dict_locked, ensure_ascii=False, indent=2)}

=== SUGGESTED DICTIONARY (CHỈ THAM KHẢO) ===
{json.dumps(dict_suggest, ensure_ascii=False, indent=2)}

=== RELATIONSHIP GRAPH ===
{json.dumps(context_pack.get("relationships_graph", []), ensure_ascii=False, indent=2)}

=== PRONOUNS & ADDRESSING ===
{json.dumps(pronouns, ensure_ascii=False, indent=2)}

=== RAW SEGMENTS TO TRANSLATE ===
{raw_text}
"""
    
    # Gọi API thực sự thông qua ai_client
    print("[Stage 3] Đang gửi Request tới AI LLM để dịch thuật...")
    
    try:
        import ai_client
        full_prompt = system_prompt + "\n\n" + user_prompt
        
        response_text = ai_client.call_ai(full_prompt, temperature=0.2, timeout=300)
        
        if not response_text:
            raise Exception("AI không trả về kết quả hoặc bị timeout toàn bộ.")
            
        # Parse JSON từ response_text
        # Có thể AI trả về kèm theo tag ```json ... ```, ta cần bóc tách
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text
            
        data = json.loads(json_str)
        
        # VALIDATE VÀ CHUẨN HÓA CẤU TRÚC JSON
        if not isinstance(data, dict):
            raise Exception(f"AI trả về {type(data).__name__}, kỳ vọng dict (JSON object).")

        # 1. Validate refined_segments
        raw_segments = data.get('refined_segments', [])
        if not isinstance(raw_segments, list):
            raw_segments = []
        clean_segments = []
        for i, seg in enumerate(raw_segments):
            if isinstance(seg, dict) and 'refined_translation' in seg:
                clean_segments.append(seg)
            elif isinstance(seg, str):
                clean_segments.append({"id": i+1, "refined_translation": seg})
        data['refined_segments'] = clean_segments

        # 2. Validate new_entities
        raw_entities = data.get('new_entities', [])
        if not isinstance(raw_entities, list):
            raw_entities = []
        clean_entities = []
        for ent in raw_entities:
            if isinstance(ent, dict) and 'raw' in ent and 'target' in ent:
                ent.setdefault('type', 'unknown')
                clean_entities.append(ent)
        data['new_entities'] = clean_entities

        # 3. Validate story_timeline
        timeline = data.get('story_timeline', {})
        if not isinstance(timeline, dict):
            data['story_timeline'] = {}
            
        print("[Stage 3] AI trả về JSON hợp lệ. Dịch thuật hoàn tất.")
        return data
    except json.JSONDecodeError as e:
        raise Exception(f"[Stage 3] Lỗi Parse JSON từ AI. Chuỗi trả về:\n{response_text[:200]}...\nLỗi: {e}")
    except Exception as e:
        raise Exception(f"[Stage 3] Giao tiếp AI lỗi: {e}")
