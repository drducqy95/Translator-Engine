import re

CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
LATIN_RE = re.compile(r'[A-Za-z]')
HANGUL_RE = re.compile(r'[\uac00-\ud7af]')
VIET_DIACRITIC_RE = re.compile(r'[ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯàáâãèéêìíòóôõùúăđĩũơưẠ-ỹ]')

KNOWN_NON_LATIN_ALIAS = {
    "培特": ["Bồi Đặc"],
    "诺文": ["Nặc Văn"],
    "蕾娜": ["Lôi Na"],
    "莫尼": ["Mạc Ni"],
    "布兰登": ["Bố Lan Đăng"],
    "格林": ["Cách Lâm"],
    "雷亚克": ["Lôi Á Khắc", "Reyak", "Reak"],
    "普兰蒂斯": ["Lan Đế Tư", "Plandis"],
    "帝释天": ["Đế Thách Thiên"],
    "罗伯特": ["La Bá Đặc"],
    "墨菲": ["Mặc Phỉ"],
    "德思礼": ["Đức Tư Lễ"],
}


def target_text(value):
    if isinstance(value, dict):
        value = value.get("target") or value.get("text") or value.get("translation") or ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").split(" (", 1)[0].strip()


def iter_locked_terms(context_pack: dict | None):
    if not context_pack:
        return
    locked = context_pack.get("locked_dictionary", {})
    if not isinstance(locked, dict):
        return
    for group in ("characters", "glossary"):
        entries = locked.get(group, {})
        if not isinstance(entries, dict):
            continue
        for raw, value in entries.items():
            raw = str(raw or "").strip()
            target = target_text(value)
            if raw and target and not CJK_RE.search(target):
                yield raw, target, group


def is_strong_entity_target(target: str) -> bool:
    if not target or CJK_RE.search(target):
        return False
    return is_foreign_like_target(target)


def is_foreign_like_target(target: str) -> bool:
    target = str(target or "").strip()
    if not target or CJK_RE.search(target):
        return False
    if HANGUL_RE.search(target):
        return True
    if VIET_DIACRITIC_RE.search(target):
        return False
    ascii_letters = len(re.findall(r'[A-Za-z]', target))
    if ascii_letters < 2:
        return False
    words = re.findall(r'[A-Za-z][A-Za-z\'-]*', target)
    return len(words) >= 1 and ascii_letters / max(len(target), 1) >= 0.55


def apply_locked_terms(text: str, context_pack: dict | None) -> str:
    if not text or not context_pack:
        return text
    replacements = {}
    for raw, target, _group in iter_locked_terms(context_pack):
        if not is_strong_entity_target(target):
            continue
        replacements[raw] = target
        for alias in KNOWN_NON_LATIN_ALIAS.get(raw, []):
            if alias and alias != target:
                replacements[alias] = target
    for src, dst in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(src, dst)
    return text


def apply_locked_terms_to_output(ai_output: dict, context_pack: dict | None) -> dict:
    if not isinstance(ai_output, dict):
        return ai_output
    for seg in ai_output.get("refined_segments", []):
        if not isinstance(seg, dict):
            continue
        seg["refined_translation"] = apply_locked_terms(str(seg.get("refined_translation", "")), context_pack)
    return ai_output
