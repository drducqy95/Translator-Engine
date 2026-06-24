import re


_CHINESE_NUMERAL_RE = re.compile(r"第?([零〇一二两兩三四五六七八九十百千万萬亿億]+)[章节回卷集篇]")
_DIGIT_CHAPTER_RE = re.compile(r"第?\s*(\d{1,6})\s*[章节回卷集篇]")


def _read_chinese_number(text):
    try:
        from numgrammar import read_number
        return read_number(text)
    except Exception:
        return None


def extract_chapter_index(chapter):
    text = ""
    if isinstance(chapter, dict):
        text = f"{chapter.get('title', '')} {chapter.get('url', '')}"
    else:
        text = str(chapter)

    match = _DIGIT_CHAPTER_RE.search(text)
    if match:
        return int(match.group(1))

    match = _CHINESE_NUMERAL_RE.search(text)
    if match:
        value = _read_chinese_number(match.group(1))
        if isinstance(value, (int, float)):
            return int(value)

    numeric_groups = re.findall(r"(\d{1,6})", text)
    if numeric_groups:
        return int(numeric_groups[-1])
    return None


def normalize_chapter_order(chapters):
    """Return chapters in reading order when a site lists newest chapters first."""
    if len(chapters) < 2:
        return chapters

    deduped = []
    seen = set()
    for chapter in reversed(chapters):
        key = chapter.get("url") if isinstance(chapter, dict) else str(chapter)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chapter)
    chapters = list(reversed(deduped))
    if len(chapters) < 2:
        return chapters

    indexed = [(pos, extract_chapter_index(chap)) for pos, chap in enumerate(chapters)]
    indexed = [(pos, idx) for pos, idx in indexed if idx is not None]
    if len(indexed) < 2:
        return chapters

    # Sort by extracted chapter index ascending when available.
    order = []
    for pos, chap in enumerate(chapters):
        idx = extract_chapter_index(chap)
        order.append((idx is None, idx if idx is not None else 10**9, pos, chap))
    sorted_order = sorted(order, key=lambda row: row[:3])
    sorted_indexed = [row[1] for row in sorted_order if not row[0]]
    if len(sorted_indexed) >= 2 and sorted_indexed == sorted(sorted_indexed):
        return [row[3] for row in sorted_order]
    return chapters


class BasePlugin:
    @property
    def source_id(self) -> str:
        raise NotImplementedError

    @property
    def source_name(self) -> str:
        raise NotImplementedError

    def search(self, keyword: str) -> list:
        return []

    def get_toc(self, novel_url: str) -> list:
        return []

    def get_metadata(self, novel_url: str) -> dict:
        return {}

    def get_chapter(self, chapter_url: str) -> str:
        return ""
