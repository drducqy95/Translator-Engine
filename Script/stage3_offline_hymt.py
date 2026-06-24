import json
import re
from ai_client import call_one_checked

CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

# ---------------------------------------------------------------------------
# JSON parser ưu tiên → fallback line-mode parse
# ---------------------------------------------------------------------------
def _extract_json_segments(text: str) -> dict[int, str]:
    raw = (text or "").strip()
    if not raw or "{" not in raw:
        return {}
    try:
        start = raw.find("{")
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for seg in data.get("refined_segments", []):
        if not isinstance(seg, dict):
            continue
        try:
            sid = int(seg.get("id"))
        except (TypeError, ValueError):
            continue
        t = seg.get("refined_translation")
        if isinstance(t, str) and t.strip():
            result[sid] = t.strip()
    return result

def _parse_line_mode(text: str, expected_ids: set[int]) -> dict[int, str]:
    segments = {}
    lines = text.split('\n')
    cur_id = None
    cur_text = []
    for line in lines:
        m = re.match(r'^\[?(\d+)\]?[\.:]?\s*(.*)', line.strip())
        if m:
            sid = int(m.group(1))
            if cur_id is not None:
                segments[cur_id] = "\n".join(cur_text).strip()
            cur_id = sid
            cur_text = [m.group(2)]
        else:
            if cur_id is not None:
                cur_text.append(line.strip())
    if cur_id is not None:
        segments[cur_id] = "\n".join(cur_text).strip()
    return {sid: val for sid, val in segments.items() if sid in expected_ids}

# ---------------------------------------------------------------------------
# Single-segment retry prompt (tối ưu cho Hy-MT)
# ---------------------------------------------------------------------------
def _single_segment_prompt(raw_text: str, sid: int, context_pack: dict):
    locked = context_pack.get("locked_dictionary", {})
    pronouns = context_pack.get("pronouns_addressing", {})
    return f"""Dịch segment [{sid}] từ Trung sang Việt.

Luật cứng:
- Chỉ trả bản dịch, không giải thích.
- KHÔNG để sót Hán tự/CJK.
- Dùng đúng Locked Dictionary.
- Giữ heading nếu là Markdown heading.

Locked Dict: {json.dumps(locked, ensure_ascii=False)}
Pronouns: {json.dumps(pronouns, ensure_ascii=False)}

{sid}: {raw_text}
"""

# ---------------------------------------------------------------------------
# RUN FALLBACK (từ Hy-MT hoặc bất kỳ provider local nào)
# ---------------------------------------------------------------------------
def run_fallback(novel_id: str, context_pack: dict, output_dir: str,
                 response_text: str, meta: dict) -> dict:
    expected_ids = [s.get("id") for s in context_pack.get("raw_segments", []) if isinstance(s, dict)]
    expected_set = set(expected_ids)

    # 1. Thử parse JSON trước
    segments = _extract_json_segments(response_text)

    # 2. Fallback line-mode
    if not segments:
        segments = _parse_line_mode(response_text, expected_set)

    refined = []
    for sid in expected_ids:
        if sid in segments and segments[sid] and not CJK_RE.search(segments[sid]):
            refined.append({"id": sid, "refined_translation": segments[sid]})
            continue

        reason = "CJK" if sid in segments and segments[sid] else "missing"
        print(f"[Stage 3 Fallback] Segment {sid} {reason}, retry single...")
        raw_seg = next((s for s in context_pack.get("raw_segments", [])
                        if isinstance(s, dict) and s.get("id") == sid), None)
        if not raw_seg:
            continue

        prompt = _single_segment_prompt(raw_seg.get("text", ""), sid, context_pack)
        ans, err = call_one_checked(meta.get("provider", "local_hymt"), prompt, timeout=60)
        if ans and not CJK_RE.search(ans):
            refined.append({"id": sid, "refined_translation": ans.strip()})
        elif err and "không thấy provider" in err:
            raise ValueError(f"Thiếu segment id: [{sid}]")
        else:
            raise ValueError(f"Fallback segment {sid} thất bại: {err or 'CJK'}")
    if not refined:
        raise ValueError("Fallback: không có segment nào dịch được")

    # Kiểm tra đủ segment
    missing = [e for e in expected_ids if e not in {s["id"] for s in refined}]
    if missing:
        raise ValueError(f"Thiếu segment id sau fallback: {missing}")

    return {
        "refined_segments": refined,
        "story_timeline": {"summary": {"main_events": "Offline fallback mode", "new_characters": []}},
        "new_entities": [],
        "relationships": [],
        "provider_meta": {"provider": meta.get("provider", "local_hymt"),
                          "mode": meta.get("mode", "offline_fallback")},
    }
