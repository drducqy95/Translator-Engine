import re

try:
    import pykakasi
except Exception:
    pykakasi = None

try:
    import hanja
except Exception:
    hanja = None

try:
    import zhconv
except Exception:
    zhconv = None

kakasi = pykakasi.kakasi() if pykakasi else None

LATIN_RE = re.compile(r"[A-Za-z]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
HIRAGANA_RE = re.compile(r"[\u3040-\u309f]")
KATAKANA_RE = re.compile(r"[\u30a0-\u30ff]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

KOREAN_SURNAMES = {
    '김': 'Kim', '이': 'Lee', '박': 'Park', '최': 'Choi', '정': 'Jung', '강': 'Kang',
    '조': 'Cho', '윤': 'Yoon', '장': 'Jang', '임': 'Lim', '한': 'Han', '신': 'Shin',
    '오': 'Oh', '서': 'Seo', '권': 'Kwon'
}

KOREAN_HANJA_SURNAMES = {
    '金': 'Kim', '李': 'Lee', '朴': 'Park', '崔': 'Choi', '郑': 'Jung', '鄭': 'Jung',
    '姜': 'Kang', '赵': 'Cho', '趙': 'Cho', '尹': 'Yoon', '张': 'Jang', '張': 'Jang',
    '林': 'Lim', '韩': 'Han', '韓': 'Han', '申': 'Shin', '吴': 'Oh', '吳': 'Oh',
    '徐': 'Seo', '权': 'Kwon', '權': 'Kwon'
}

KOREAN_HANJA_NAME_OVERRIDES = {
    '朴智星': 'Park Ji-sung',
    '金秀贤': 'Kim Soo-hyun',
    '金秀賢': 'Kim Soo-hyun',
    '李敏镐': 'Lee Min-ho',
    '李敏鎬': 'Lee Min-ho',
}

JAPANESE_SPECIAL_NAMES = {
    '宇智波': 'Uchiha', '漩涡': 'Uzumaki', '日向': 'Hyuga', '大筒木': 'Otsutsuki',
    '千手': 'Senju', '波风': 'Namikaze', '春野': 'Haruno', '旗木': 'Hatake'
}

JAPANESE_GIVEN_OVERRIDES = {
    '佐助': 'Sasuke', '鸣人': 'Naruto', '鳴人': 'Naruto', '健': 'Takeru',
}

JAPANESE_FULL_NAME_OVERRIDES = {
    '佐藤健': 'Sato Takeru',
}


def _romanize_japanese(text: str) -> str:
    if not text:
        return ""
    remaining = text
    parts = []
    for kanji, romaji in JAPANESE_SPECIAL_NAMES.items():
        if remaining.startswith(kanji):
            parts.append(romaji)
            remaining = remaining[len(kanji):]
            break
    if remaining in JAPANESE_GIVEN_OVERRIDES:
        parts.append(JAPANESE_GIVEN_OVERRIDES[remaining])
        remaining = ""
    if remaining and kakasi:
        try:
            src = zhconv.convert(remaining, 'zh-hant') if zhconv else remaining
            result = kakasi.convert(src)
            romanized = "".join(item.get('hepburn') or item.get('kunrei') or item.get('kana') or '' for item in result)
            parts.append(romanized[:1].upper() + romanized[1:] if romanized else "")
        except Exception:
            parts.append(remaining)
    elif remaining:
        parts.append(remaining)
    converted = "".join(parts)
    return "" if CJK_RE.search(converted) else converted


def analyze_and_convert_entity(entity: str) -> dict | None:
    entity = (entity or "").strip()
    if len(entity) < 2:
        return None

    entity = re.sub(r"\s+", " ", entity)

    if entity in JAPANESE_FULL_NAME_OVERRIDES:
        return {"type": "Japanese", "converted": JAPANESE_FULL_NAME_OVERRIDES[entity]}

    if LATIN_RE.search(entity) and not CJK_RE.search(entity):
        return {"type": "Latin", "converted": entity.strip(" _-.")}

    if HANGUL_RE.search(entity):
        first = entity[0]
        if first in KOREAN_SURNAMES:
            tail = entity[1:]
            if hanja is not None:
                try:
                    tail = hanja.translate(tail, 'substitution')
                except Exception:
                    pass
            return {"type": "Korean", "converted": f"{KOREAN_SURNAMES[first]} {tail}".strip()}
        return {"type": "Korean", "converted": entity}

    if CJK_RE.search(entity):
        if entity in JAPANESE_FULL_NAME_OVERRIDES:
            return {"type": "Japanese", "converted": JAPANESE_FULL_NAME_OVERRIDES[entity]}
        if any(entity.startswith(prefix) for prefix in JAPANESE_SPECIAL_NAMES) or HIRAGANA_RE.search(entity) or KATAKANA_RE.search(entity):
            converted = _romanize_japanese(entity)
            return {"type": "Japanese", "converted": converted} if converted else None
        if entity in KOREAN_HANJA_NAME_OVERRIDES:
            return {"type": "Korean", "converted": KOREAN_HANJA_NAME_OVERRIDES[entity]}
        if len(entity) >= 2 and entity[0] in KOREAN_HANJA_SURNAMES:
            converted = f"{KOREAN_HANJA_SURNAMES[entity[0]]} {entity[1:]}".strip()
            return {"type": "Korean", "converted": converted} if not CJK_RE.search(converted) else None

        # Nếu không nhận ra là Hàn, thử romanize như tên Nhật để tránh rơi về Hán-Việt sai.
        converted = _romanize_japanese(entity)
        if converted and not CJK_RE.search(converted):
            return {"type": "Japanese", "converted": converted}

    return None


if __name__ == '__main__':
    for t in ["宇智波佐助", "漩涡鸣人", "김수현", "ハル", "佐藤健", "朴智星", "Pette Chinar"]:
        print(f"{t}: {analyze_and_convert_entity(t)}")
