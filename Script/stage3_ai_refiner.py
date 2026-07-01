import json
import re
from pathlib import Path
try:
    from entity_locks import apply_locked_terms_to_output
except ImportError:
    from Script.entity_locks import apply_locked_terms_to_output

_CJK = None
def _has_cjk(s):
    global _CJK
    if _CJK is None:
        _CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
    return bool(_CJK.search(s))

def _trim_context(cp: dict) -> dict:
    """Chỉ giữ locked dict terms có trong raw_segments."""
    segs_text = " ".join(s.get("text","") for s in cp.get("raw_segments",[]) if isinstance(s,dict))
    result = dict(cp)
    for key in ("locked_dictionary","suggested_dictionary"):
        d = cp.get(key,{})
        if isinstance(d,dict):
            trimmed = {}
            for group, values in d.items():
                if isinstance(values, dict):
                    trimmed[group] = {raw: target for raw, target in values.items() if raw and raw in segs_text}
                elif group and group in segs_text:
                    trimmed[group] = values
            result[key] = trimmed
    return result

def build_stage3_prompt(context_pack: dict) -> str:
    config = context_pack.get("translation_config", {})
    goal = config.get("translation_goal", {})
    style = goal.get("style", "văn xuôi tiếng Việt mượt")
    anti_goals = goal.get("anti_goals", [])
    segs = context_pack.get("raw_segments", [])
    ids = [s.get("id") for s in segs if isinstance(s, dict)]
    rules = [
        f"Bạn là biên dịch viên văn học Trung→Việt.",
        f"Phong cách: {style}",
        "",
        "QUY TẮC CỨNG:",
        "1. Locked Dictionary: BẮT BUỘC dùng target đã khóa. KHÔNG dùng raw/tên gốc.",
        "   Entity Latin/Nhật/Hàn đã có target Latin/Romaji/Hangul-Latin thì PHẢI dùng đúng target; cấm Hán Việt hóa.",
        "2. RAW là bản Trung gốc; QT là bản dịch máy/QT. Nhiệm vụ chính: hiệu chỉnh QT thành văn Việt tự nhiên, đối chiếu RAW để sửa sai nghĩa.",
        "2b. Suggested Dictionary là entity mới phát hiện; với tên riêng/nhân vật/địa danh, hãy dùng target đã gợi ý nếu không mâu thuẫn context.",
        "3. KHÔNG sót ký tự CJK.",
        f"4. Giữ đúng số lượng, thứ tự, id. Expected IDs: {ids}.",
        "4. Heading Markdown → giữ heading.",
        "5. Chỉ output JSON, không giải thích.",
        "6. Trích xuất entity mới vào new_entities.",
        "7. Đề xuất grammar_notes khi phát hiện mẫu dịch/xưng hô/cụm cố định cần khóa.",
        "8. Tóm tắt story timeline 1-2 câu.",
        "",
        "SCHEMA OUTPUT:",
        json.dumps({
            "refined_segments": [{"id": 1, "refined_translation": "# Chương 0001 ..."}],
            "story_timeline": {"summary": {"main_events": "...", "new_characters": []}},
            "new_entities": [{"raw": "中文名", "target": "Tên Việt", "type": "character", "origin": "chinese", "name_type": "person"}],
            "relationships": [{"source": "A", "target": "B", "relationship": "ally_of"}],
            "grammar_notes": []
        }, ensure_ascii=False, indent=2)
    ]
    for a in (anti_goals or [])[:5]:
        rules.insert(3, f"- Tránh: {a}")
    rules.insert(4, f"- IDs = {ids}")
    return "\n".join(rules)

def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text: raise ValueError("AI trả về rỗng")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence: text = fence.group(1).strip()
    start = text.find("{")
    if start < 0: raise ValueError("Không tìm thấy JSON object")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON không hợp lệ: {e}")
    if not isinstance(data, dict): raise ValueError("AI không trả dict")
    return data

def _normalize_output(data: dict, expected_segments: list[dict]) -> dict:
    expected_ids = [s.get("id") for s in expected_segments if isinstance(s, dict)]
    segment_id_map = {s.get("id"): s.get("segment_id") for s in expected_segments if isinstance(s, dict)}
    raw = data.get("refined_segments", [])
    if not isinstance(raw, list): raise ValueError("refined_segments phải là list")
    seen, clean, errors = set(), [], []
    for s in raw:
        if isinstance(s, str): s = {"id": len(seen)+1, "refined_translation": s}
        if not isinstance(s, dict): continue
        sid = s.get("id")
        try: sid = int(sid)
        except: errors.append("segment thiếu id"); continue
        t = s.get("refined_translation","")
        if not isinstance(t, str) or not t.strip(): errors.append(f"seg {sid} thiếu text"); continue
        if sid in seen: errors.append(f"trùng id {sid}"); continue
        item = {"id": sid, "refined_translation": t.strip()}
        if segment_id_map.get(sid):
            item["segment_id"] = segment_id_map[sid]
        clean.append(item)
        seen.add(sid)
    missing = [e for e in expected_ids if e not in seen]
    if missing: errors.append(f"Thiếu segment id: {missing}")
    if errors: raise ValueError("; ".join(errors))
    order = {e:i for i,e in enumerate(expected_ids)}
    data["refined_segments"] = sorted(clean, key=lambda x: order.get(x["id"],10**9))
    data.setdefault("new_entities",[]); data.setdefault("relationships",[]); data.setdefault("grammar_notes",[])
    return data

def run(novel_id: str, context_pack: dict, output_dir: str) -> dict:
    print(f"[Stage 3] AI Refiner: {novel_id}")

    cp = _trim_context(context_pack)
    n_segs = len(cp.get("raw_segments", []))
    print(f"[Stage 3] {n_segs} segments")

    # Build prompt
    system_prompt = build_stage3_prompt(cp)
    seg_text = "\n".join(
        f"[{s['id']}]\nRAW: {s.get('text','')}\nQT: {s.get('qt','')}"
        for s in cp.get("raw_segments",[]) if isinstance(s,dict)
    )
    locked = cp.get("locked_dictionary",{})
    suggest = cp.get("suggested_dictionary",{})
    pronouns = cp.get("pronouns_addressing",{})
    tm_hits = cp.get("translation_memory_hits",[])

    user_prompt = f"""=== LOCKED DICTIONARY ===
{json.dumps(locked, ensure_ascii=False)}
=== SUGGESTED DICTIONARY ===
{json.dumps(suggest, ensure_ascii=False)}
=== PRONOUNS ===
{json.dumps(pronouns, ensure_ascii=False)}
=== TRANSLATION MEMORY ===
{json.dumps(tm_hits, ensure_ascii=False)[:400]}
=== SEGMENTS (RAW + QT DRAFT) ===
{seg_text}"""

    print("[Stage 3] Gọi AI...")
    import ai_client
    response_text, ai_err, meta = ai_client.call_ai_checked_with_meta(
        user_prompt, system_prompt=system_prompt, temperature=0.2, timeout=900, max_retries=3)

    if ai_err or not response_text:
        raise Exception(f"AI failed: {ai_err}")

    try:
        data = _extract_json_object(response_text)
        data = _normalize_output(data, [s for s in cp.get("raw_segments",[]) if isinstance(s,dict)])
    except Exception as je:
        print(f"[Stage 3] JSON fail, fallback: {je}")
        import stage3_offline_hymt
        meta_safe = meta or {"provider":"fallback","mode":"fallback"}
        data = stage3_offline_hymt.run_fallback(novel_id, cp, output_dir, response_text, meta_safe)

    data = apply_locked_terms_to_output(data, cp)

    # Validate đủ segment
    all_ids = [s.get("id") for s in context_pack.get("raw_segments",[]) if isinstance(s,dict)]
    got_ids = [s["id"] for s in data.get("refined_segments",[])]
    missing = [e for e in all_ids if e not in got_ids]
    if missing: raise ValueError(f"Thiếu segment: {missing}")

    cjk = [s for s in data["refined_segments"] if _has_cjk(s.get("refined_translation", ""))]
    if cjk:
        print(f"[Stage 3] CJK residue in segments {[s['id'] for s in cjk]}, trying segment fallback...")
        import stage3_offline_hymt
        meta_safe = meta or {"provider": "fallback", "mode": "fallback"}
        try:
            data = stage3_offline_hymt.run_fallback(novel_id, cp, output_dir, json.dumps(data, ensure_ascii=False), meta_safe)
        except Exception as fb_err:
            raise ValueError(f"CJK trong segments: {[s['id'] for s in cjk]}; fallback failed: {fb_err}")
        cjk = [s for s in data["refined_segments"] if _has_cjk(s.get("refined_translation", ""))]
        if cjk:
            raise ValueError(f"CJK trong segments: {[s['id'] for s in cjk]}")

    data["provider_meta"] = meta or {"provider":"online","mode":"online"}
    print("[Stage 3] OK"); return data
