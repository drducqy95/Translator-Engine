#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chinese number / currency / time / measure-word reading for the QT draft.

Generates readings instead of storing 14k static number rows (many of which are wrong,
e.g. 一万年零六百 -> 10.600). The translator calls read_number_span on a run of
number+unit characters and gets a clean Vietnamese rendering.

Public API:
    read_number(han) -> int|float|None      pure number ('一万三千五十' -> 13050)
    read_number_span(han) -> str|None        number + unit ('三个' -> '3 cái', '三点半' -> '3 giờ rưỡi')
    is_number_char(ch) -> bool               ch participates in a number/unit span
"""
import re

# Digit + place-value characters of the Chinese numeral system.
_DIGIT = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '兩': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
}
_SMALL_UNIT = {'十': 10, '百': 100, '千': 1000}
_BIG_UNIT = {'万': 10**4, '萬': 10**4, '亿': 10**8, '億': 10**8}
_DECIMAL_MARK = '点'   # 二点五 -> 2.5 (only inside a number context)

# Measure words (classifiers): rendered AFTER the number, Vietnamese order.
# Frequency-ranked on 10 chapters of Chu Than Dai Dao + common cultivation classifiers.
_MEASURE = {
    '个': 'cái', '個': 'cái', '位': 'vị', '道': 'đạo', '座': 'tòa', '名': 'người',
    '条': 'con', '條': 'con', '只': 'con', '隻': 'con', '头': 'con', '頭': 'con',
    '颗': 'viên', '顆': 'viên', '粒': 'hạt', '块': 'khối', '塊': 'khối',
    '张': 'tấm', '張': 'tấm', '把': 'cây', '支': 'cây', '根': 'cây',
    '本': 'quyển', '部': 'bộ', '件': 'kiện', '层': 'tầng', '層': 'tầng',
    '种': 'loại', '種': 'loại', '群': 'đám', '排': 'hàng', '队': 'đội',
}

# Currency units (rendered after the number).
_CURRENCY = {
    '元': 'tệ', '块': 'đồng', '块钱': 'đồng', '塊錢': 'đồng',
    '美元': 'đô la Mỹ', '美金': 'đô la Mỹ', '日元': 'yên', '欧元': 'euro',
    '英镑': 'bảng Anh', '韩元': 'won', '卢布': 'rúp',
}

# Time units. 点/点钟 -> giờ; others straightforward.
_TIME = {
    '点': 'giờ', '点钟': 'giờ', '點': 'giờ', '分': 'phút', '秒': 'giây',
    '小时': 'tiếng', '小時': 'tiếng', '分钟': 'phút', '分鐘': 'phút',
}

# Weekday: 星期/周/礼拜 + digit. 星期三 -> thứ Tư, 星期日/天 -> Chủ nhật.
_WEEKDAY_HEAD = ('星期', '周', '週', '礼拜', '禮拜')
_WEEKDAY_NAME = {1: 'thứ Hai', 2: 'thứ Ba', 3: 'thứ Tư', 4: 'thứ Năm',
                 5: 'thứ Sáu', 6: 'thứ Bảy'}

_NUM_CHARS = set(_DIGIT) | set(_SMALL_UNIT) | set(_BIG_UNIT) | {_DECIMAL_MARK}


def is_number_char(ch):
    return ch in _NUM_CHARS


# Single-char unit heads (the FIRST char of any currency/time/measure unit). Used to decide
# whether the token(s) right after a number run might form a unit worth absorbing.
_UNIT_HEADS = {u[0] for tbl in (_CURRENCY, _TIME, _MEASURE) for u in tbl}
_UNIT_HEADS |= {h[0] for h in _WEEKDAY_HEAD}


def _all_number_chars(s):
    return bool(s) and all(is_number_char(c) for c in s)


def apply_numbers(tokens, log=False):
    """Merge consecutive number-char tokens (+ an optional trailing unit token) into ONE
    rendered 'number' node, generating the reading via read_number_span. Same token-stream
    contract as grammar.apply_de: tokens are {'src','tgt','pos','kind'}; returns a new list.

    A weekday run (星期三) is unit-LED, so also try absorbing a leading 星期/周/礼拜 token."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        src = (tok.get('src') or '').strip()

        # Weekday: a token starting with a weekday head, optionally + a following digit token.
        wk = None
        if any(src.startswith(h) for h in _WEEKDAY_HEAD):
            combined = src
            j = i + 1
            # absorb following number/日/天 token if the head alone has no day yet
            if combined in _WEEKDAY_HEAD and j < n:
                nxt = (tokens[j].get('src') or '').strip()
                if _all_number_chars(nxt) or nxt in ('日', '天'):
                    combined += nxt
                    j += 1
            wk = read_number_span(combined)
            if wk:
                out.append({'src': combined, 'tgt': wk, 'pos': None, 'kind': 'number'})
                i = j
                continue

        # Numeric run: gather consecutive number-char tokens.
        if _all_number_chars(src):
            run = src
            j = i + 1
            while j < n and _all_number_chars((tokens[j].get('src') or '').strip()):
                run += (tokens[j].get('src') or '').strip()
                j += 1
            # Absorb up to TWO trailing unit tokens so a measure+unit pair survives
            # (四 + 个 + 小时 -> '四个小时' -> '4 tiếng'). Try the longer span first.
            units = []
            k = j
            while k < n and len(units) < 2:
                cand = (tokens[k].get('src') or '').strip()
                if cand and cand[0] in _UNIT_HEADS and not _all_number_chars(cand):
                    units.append(cand)
                    k += 1
                else:
                    break
            rendered = None
            consumed = j
            for take in range(len(units), -1, -1):
                unit_src = ''.join(units[:take])
                r = read_number_span(run + unit_src)
                if r is not None:
                    rendered = r
                    consumed = j + take
                    break
            if rendered is not None:
                out.append({'src': run + ''.join(units[:consumed - j]),
                            'tgt': rendered, 'pos': None, 'kind': 'number'})
                i = consumed
                continue

        out.append(tok)
        i += 1
    return out


def _num_run_len(text, i):
    """Length of the maximal leading run of number chars (Han numerals + ASCII digits) at i."""
    k, n = i, len(text)
    while k < n and (is_number_char(text[k]) or text[k].isdigit()):
        k += 1
    return k - i


def match_at(text, i):
    """Read a number(+unit) span starting at text[i]. Returns (length, rendered) or None.

    Called by the translator DP as a FIRST-CLASS candidate so a number span beats a
    garbage dict term (三位 -> '3 vị', not the lacviet 'TAM VỊ...' gloss) and so a digit
    led span works (4个小时 -> '4 tiếng'). Longest valid span wins (units beat bare num)."""
    n = len(text)
    # Weekday: head + (digit | 日 | 天)
    for head in _WEEKDAY_HEAD:
        if text.startswith(head, i):
            j = i + len(head)
            if j < n and (is_number_char(text[j]) or text[j].isdigit()
                          or text[j] in ('日', '天')):
                r = read_number_span(text[i:j + 1])
                if r:
                    return (len(head) + 1, r)
    is_ordinal = False
    start_idx = i
    if text[i] == '第':
        is_ordinal = True
        start_idx = i + 1

    run = _num_run_len(text, start_idx)
    if run == 0:
        return None
        
    base_end = start_idx + run
    # Absorb up to 3 trailing unit chars; longest span that renders wins (个小时 over 个).
    for take in range(3, -1, -1):
        if base_end + take > n:
            continue
        span = text[i:base_end + take]
        r = read_number_span(span)
        if r is not None:
            return (len(span), r)
    return None


def _read_int_section(s):
    """Read a <10000 section written with 十/百/千 (e.g. '三千五十' -> 3050)."""
    if not s:
        return None
    total = 0
    current = 0
    seen = False
    for ch in s:
        if ch in _DIGIT:
            current = _DIGIT[ch]
            seen = True
        elif ch in _SMALL_UNIT:
            unit = _SMALL_UNIT[ch]
            # '十' with no preceding digit means 1 (十五 -> 15)
            total += (current or 1) * unit
            current = 0
            seen = True
        else:
            return None
    total += current
    return total if seen else None


def read_number(han):
    """Parse a Chinese numeral string to int or float. Returns None if not a clean number.
    Handles nested big units (万/亿), 零 as a place-skip, and 点 decimals."""
    if not han:
        return None
    han = han.strip()
    if not han:
        return None

    # Decimal: split on 点 once. Left side integer, right side digit-by-digit.
    if _DECIMAL_MARK in han:
        left, _, right = han.partition(_DECIMAL_MARK)
        ip = read_number(left) if left else 0
        if ip is None or not right:
            return None
        frac_digits = []
        for ch in right:
            if ch not in _DIGIT:
                return None
            frac_digits.append(str(_DIGIT[ch]))
        try:
            return float(f'{int(ip)}.{"".join(frac_digits)}')
        except ValueError:
            return None

    # Pure arabic already?
    if han.isdigit():
        return int(han)

    # Split on big units (亿 then 万), recursively reading each section.
    for big_ch, big_val in (('亿', 10**8), ('億', 10**8), ('万', 10**4), ('萬', 10**4)):
        if big_ch in han:
            left, _, right = han.partition(big_ch)
            lv = read_number(left) if left else 1
            if lv is None:
                return None
            # 零 right after a big unit is a place-skip: 一万零三百 -> 10300
            right = right.lstrip('零〇')
            rv = read_number(right) if right else 0
            if rv is None:
                return None
            return lv * big_val + rv

    # Section below 10000.
    han = han.replace('零', '').replace('〇', '')
    if not han:
        return 0
    # all bare digits with no place units: read as a digit sequence (一二三 -> 123)
    if all(c in _DIGIT for c in han):
        if len(han) == 1:
            return _DIGIT[han]
        return int(''.join(str(_DIGIT[c]) for c in han))
    return _read_int_section(han)


def _fmt(n):
    """Format a parsed number for Vietnamese output (integers bare, floats with comma)."""
    if isinstance(n, float):
        if n.is_integer():
            return str(int(n))
        return str(n).replace('.', ',')   # VN decimal comma
    return str(n)


def read_number_span(han):
    """Read a number(+unit) span to Vietnamese, or None if it isn't one.
    '三个'->'3 cái', '三点半'->'3 giờ rưỡi', '五美元'->'5 đô la Mỹ', '星期三'->'thứ Tư'."""
    if not han:
        return None
    han = han.strip()

    # Ordinal (第 + Number + Unit)
    if han.startswith('第'):
        rest = han[1:]
        m = re.match(r'^(.+?)(章|卷|季|集|篇|回|名|天|日|次|步|代)$', rest)
        if m:
            n = read_number(m.group(1))
            if n is not None:
                unit = m.group(2)
                v_num = _fmt(n)
                if unit in ('章', '卷', '季', '集', '篇', '回'):
                    v_unit = {'章': 'chương', '卷': 'quyển', '季': 'mùa', '集': 'tập', '篇': 'thiên', '回': 'hồi'}[unit]
                    return f'{v_unit} {v_num}'
                elif unit == '名':
                    return f'hạng {v_num}'
                elif unit in ('天', '日'):
                    return f'ngày thứ {v_num}'
                elif unit == '次':
                    return f'lần thứ {v_num}'
                elif unit == '步':
                    return f'bước thứ {v_num}'
                elif unit == '代':
                    return f'đời thứ {v_num}'

        for table in (_CURRENCY, _TIME, _MEASURE):
            for unit in sorted(table, key=len, reverse=True):
                if rest.endswith(unit) and len(rest) > len(unit):
                    num_part = rest[:-len(unit)]
                    n = read_number(num_part)
                    if n is not None:
                        return f'{table[unit]} thứ {_fmt(n)}'

        n = read_number(rest)
        if n is not None:
            return f'thứ {_fmt(n)}'
        
        return None

    # Weekday: 星期/周/礼拜 + digit or 日/天
    for head in _WEEKDAY_HEAD:
        if han.startswith(head):
            rest = han[len(head):]
            if rest in ('日', '天'):
                return 'Chủ nhật'
            d = read_number(rest)
            if d in _WEEKDAY_NAME:
                return _WEEKDAY_NAME[d]
            return None

    # 'N点半' -> 'N giờ rưỡi'
    m = re.match(r'^(.+?)点半$', han)
    if m:
        n = read_number(m.group(1))
        if n is not None:
            return f'{_fmt(n)} giờ rưỡi'

    # Duration: 'N个 + time-unit' — 个 here is a counter before a span, not '个=cái'.
    # 四个小时 -> '4 tiếng', 三个月 -> '3 tháng', 三个星期 -> '3 tuần'.
    m = re.match(r'^(.+?)个(小时|小時|月|星期|礼拜|禮拜|周|週|钟头|鐘頭)$', han)
    if m:
        n = read_number(m.group(1))
        if n is not None:
            span_unit = {'小时': 'tiếng', '小時': 'tiếng', '钟头': 'tiếng', '鐘頭': 'tiếng',
                         '月': 'tháng', '星期': 'tuần', '礼拜': 'tuần', '禮拜': 'tuần',
                         '周': 'tuần', '週': 'tuần'}[m.group(2)]
            return f'{_fmt(n)} {span_unit}'

    # number + (multi-char unit first, then single-char) — currency / time / measure
    for table in (_CURRENCY, _TIME, _MEASURE):
        # try longer unit keys first so 块钱 wins over 块
        for unit in sorted(table, key=len, reverse=True):
            if han.endswith(unit) and len(han) > len(unit):
                num_part = han[:-len(unit)]
                n = read_number(num_part)
                if n is not None:
                    return f'{_fmt(n)} {table[unit]}'

    # bare number
    n = read_number(han)
    if n is not None:
        return _fmt(n)
    return None
