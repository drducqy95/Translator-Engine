#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Transbot chapter splitter.

Input : Transbot/Source/Source full/*
Output: Transbot/Source/Source Split/<branch>/Chapter 0001 <title>.md

Supports headings such as:
- 第1章 标题
- 406.第403章 聚众看片
- 第001章 标题
- 第四百二十一章 标题
- 第1回 标题
- 第1节 标题
- Chương 1: Tiêu đề
- Chapter 1: Title
"""

from pathlib import Path
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

# Constants removed.

CN_NUM = {
    '零': 0, '〇': 0, '○': 0,
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10, '百': 100, '千': 1000, '万': 10000,
}


def remove_diacritics(text: str) -> str:
    text = unicodedata.normalize('NFD', text)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    return text.replace('Đ', 'D').replace('đ', 'd')


def branch_name_from_full_file(path: Path) -> str:
    name = path.stem
    story_title = name.split('_', 1)[0].strip()
    branch = remove_diacritics(story_title)
    branch = re.sub(r'[^\w\s-]', '', branch, flags=re.UNICODE)
    branch = re.sub(r'\s+', ' ', branch).strip()
    return branch or remove_diacritics(name)


def safe_filename_part(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:120] if len(text) > 120 else text


def chinese_numeral_to_int(s: str):
    s = s.replace('兩', '二').replace('两', '二').replace('〇', '零').replace('○', '零')
    if not s:
        return None
    if s.isdigit():
        return int(s)

    total = 0
    section = 0
    number = 0
    has_cn = False

    for ch in s:
        if ch in CN_NUM:
            has_cn = True
            val = CN_NUM[ch]
            if val < 10:
                number = val
            elif val == 10:
                if number == 0:
                    number = 1
                section += number * 10
                number = 0
            elif val == 100:
                if number == 0:
                    number = 1
                section += number * 100
                number = 0
            elif val == 1000:
                if number == 0:
                    number = 1
                section += number * 1000
                number = 0
            elif val == 10000:
                section += number
                total += section * 10000
                section = 0
                number = 0
        else:
            return None

    if not has_cn:
        return None
    return total + section + number


def normalize_heading(s: str) -> str:
    s = s.strip().lstrip('\ufeff')
    s = s.replace('　', ' ')
    s = re.sub(r'^\s*\d+\s*[\.\-、:]\s*', '', s)
    # Strip an optional volume prefix so '第十三卷 第七十二章 ...' and the named form
    # '第三卷 新邻居 第二十三章 ...' both expose the '第…章 …' part to the chapter scan.
    # The volume name (e.g. 新邻居) sits between '第N卷' and the next '第', so consume
    # everything up to that next '第'. split_file uses a sequential seq_num for filenames,
    # so the per-volume chapter number reset is harmless. A volume-only heading
    # ('第三卷 新邻居' with no chapter) collapses to '' and is correctly ignored.
    # Strip a leading volume prefix only when a real chapter marker (第<num>章/节/回)
    # follows. Handles '第十三卷 第七十二章 ...', a named volume '第四卷 幽灵饭店 第六十一章 ...',
    # and a malformed prefix missing 卷 ('第十四 第八十五章 ...'). The lookahead keeps a
    # plain '第八十五章 祭祀' untouched (nothing to strip).
    s = re.sub(
        r'^第\s*[0-9０-９零〇○一二三四五六七八九十百千万兩两]+\s*卷?[^第]*'
        r'(?=第\s*[0-9０-９零〇○一二三四五六七八九十百千万兩两]+\s*[章节回])',
        '', s)
    return s.strip()


def detect_chapter_heading(line: str):
    s = normalize_heading(line)
    if not s:
        return None

    # Reject two running-text false positives that otherwise satisfy '^第N章/回':
    #   1. mid-body recaps that end in a full-width colon ('第十三卷第三十八章真正的恐怖电影：'),
    #   2. '第一回合…' (回合 = a round/bout, not a 回 chapter).
    # Real chapter headings never end in '：' and never use 回合.
    if s.rstrip().endswith('：'):
        return None
    if re.match(r'^第\s*[0-9０-９零〇○一二三四五六七八九十百千万兩两]+\s*回合', s):
        return None

    # Chinese numeric: 第403章, 第003章, 第1回, etc.
    # Require separator (space/punct) after 章/节/回 to avoid false matches in running text
    m = re.match(r'^第\s*([0-9０-９]+)\s*[章节回](?:[\s:：、.．\-—–]+|(?=[一-鿿])|$)(.*)$', s)
    if m:
        raw_num = m.group(1).translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        title = m.group(2).strip() or s
        return int(raw_num), title, s

    # Chinese numeral: 第四百二十一章, 第一章
    m = re.match(r'^第\s*([零〇○一二三四五六七八九十百千万兩两]+)\s*[章节回](?:[\s:：、.．\-—–]+|(?=[一-鿿])|$)(.*)$', s)
    if m:
        num = chinese_numeral_to_int(m.group(1))
        if num is not None:
            title = m.group(2).strip() or s
            return int(num), title, s

    # Vietnamese / English.
    m = re.match(r'^(?:Chương|Chapter|CHƯƠNG|Chap|CHAP)\s*([0-9]+)\s*[:：\-—–]?\s*(.*)$', s, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        title = m.group(2).strip() or s
        return num, title, s

    # Non-numbered chapter markers commonly present in Chinese web novels.
    # They are real <h1> chapters in many full-source dumps, so keep them as
    # split boundaries instead of dropping author notices or final remarks.
    compact = re.sub(r'\s+', '', s)
    if 2 <= len(compact) <= 80:
        looks_like_sentence = (
            s.lstrip().startswith(('（', '(', '“', '"', '【', '['))
            or compact.endswith(('。', '！', '？', '；', '…', '”', '"', '）', ')', '】', ']', '.', '!', '?'))
        )
        if not looks_like_sentence:
            notice_keywords = (
                '上架', '请假', '請假', '请假条', '感言', '完本感言',
                '后记', '後記', '番外', '停更', '致读者', '致讀者',
            )
            if any(key in compact for key in notice_keywords):
                return 0, s, s

        # Volume-only headings occasionally encode a source chapter boundary
        # even when they do not contain 章/节/回, e.g. '第十卷 ... 第十三卷 ...'.
        if re.match(r'^第[0-9０-９零〇○一二三四五六七八九十百千万兩两]+卷', compact):
            return 0, s, s

    return None


# Block-level HTML tags whose boundaries must become line breaks, so a heading
# wrapped in <h1>/<p>/<title> lands on its own line for detect_chapter_heading.
_HTML_BLOCK = {'p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li',
               'tr', 'section', 'article', 'body', 'title', 'blockquote', 'hr'}
# Only containers with real open/close tags belong here. Void elements like <meta>
# and <link> have no end tag, so counting them as skip-depth would never decrement
# and would swallow the whole document; they live inside <head> and are skipped anyway.
_HTML_SKIP = {'script', 'style', 'head'}


class _HTMLToLines(HTMLParser):
    """Collapse HTML into plain text, inserting a newline at every block boundary.
    Content inside <script>/<style>/<head> is dropped."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HTML_SKIP:
            self._skip_depth += 1
        elif tag in _HTML_BLOCK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in _HTML_SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _HTML_BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.parts.append(data)

    def text(self):
        return ''.join(self.parts)


def _html_bytes_to_lines(raw: bytes):
    """Decode HTML bytes (best-effort encoding) and flatten to text lines."""
    try:
        html = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        # fall back to charset in a <meta>, else latin-1 so nothing is lost
        m = re.search(br'charset=["\']?\s*([\w-]+)', raw[:2048], re.IGNORECASE)
        enc = m.group(1).decode('ascii', 'replace') if m else 'latin-1'
        try:
            html = raw.decode(enc, errors='replace')
        except (LookupError, UnicodeDecodeError):
            html = raw.decode('latin-1', errors='replace')
    p = _HTMLToLines()
    p.feed(html)
    return [ln + '\n' for ln in p.text().splitlines()]


def _extract_html(path: Path):
    return _html_bytes_to_lines(path.read_bytes())


def _extract_epub(path: Path):
    """EPUB = zip of XHTML docs. Read the OPF spine for reading order, flatten each
    document to lines, and concatenate. Falls back to sorted *.xhtml if the OPF is
    unreadable, so a malformed package still yields text."""
    lines = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        opf_name = None
        # container.xml points at the OPF; tolerate its absence.
        if 'META-INF/container.xml' in names:
            try:
                root = ET.fromstring(z.read('META-INF/container.xml'))
                for rf in root.iter():
                    if rf.tag.endswith('rootfile'):
                        opf_name = rf.attrib.get('full-path')
                        break
            except ET.ParseError:
                pass
        spine_files = []
        if opf_name and opf_name in names:
            try:
                opf = ET.fromstring(z.read(opf_name))
                manifest = {}
                for el in opf.iter():
                    if el.tag.endswith('item'):
                        manifest[el.attrib.get('id')] = el.attrib.get('href')
                base = opf_name.rsplit('/', 1)[0] if '/' in opf_name else ''
                for el in opf.iter():
                    if el.tag.endswith('itemref'):
                        href = manifest.get(el.attrib.get('idref'))
                        if not href:
                            continue
                        full = f'{base}/{href}' if base else href
                        # normalize ../ and ./ segments against the zip flat namespace
                        full = re.sub(r'[^/]+/\.\./', '', full).lstrip('./')
                        if full in names:
                            spine_files.append(full)
            except ET.ParseError:
                pass
        if not spine_files:
            spine_files = sorted(n for n in names
                                 if n.lower().endswith(('.xhtml', '.html', '.htm')))
        for fn in spine_files:
            try:
                lines.extend(_html_bytes_to_lines(z.read(fn)))
            except KeyError:
                continue
    return lines


def _extract_docx(path: Path):
    """DOCX = zip; word/document.xml holds the body. Each <w:p> is one paragraph
    (joined <w:t> runs); <w:br>/<w:tab> become whitespace."""
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    lines = []
    with zipfile.ZipFile(path) as z:
        if 'word/document.xml' not in z.namelist():
            return lines
        root = ET.fromstring(z.read('word/document.xml'))
        for para in root.iter(f'{W}p'):
            buf = []
            for node in para.iter():
                if node.tag == f'{W}t' and node.text:
                    buf.append(node.text)
                elif node.tag in (f'{W}br', f'{W}cr'):
                    buf.append(' ')
                elif node.tag == f'{W}tab':
                    buf.append(' ')
            lines.append(''.join(buf) + '\n')
    return lines


def extract_lines(path: Path):
    """Return a list of text lines (with trailing newlines) for any supported source
    format. Every format is reduced to lines so the shared detect_chapter_heading scan
    works identically. Unknown extensions are read as plain text."""
    suffix = path.suffix.lower()
    if suffix in ('.html', '.htm', '.xhtml'):
        return _extract_html(path)
    if suffix == '.epub':
        return _extract_epub(path)
    if suffix == '.docx':
        return _extract_docx(path)
    # .txt and anything else: treat as UTF-8 text.
    return path.read_text(encoding='utf-8-sig', errors='replace').splitlines(keepends=True)


# Transbot constants removed. Use as a library.
