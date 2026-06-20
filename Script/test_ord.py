from numgrammar import *

def patched_match_at(text, i):
    n = len(text)
    for head in _WEEKDAY_HEAD:
        if text.startswith(head, i):
            j = i + len(head)
            if j < n and (is_number_char(text[j]) or text[j].isdigit() or text[j] in ('日', '天')):
                r = patched_read_number_span(text[i:j + 1])
                if r: return (len(head) + 1, r)
    is_ordinal = False
    start_idx = i
    if text[i] == '第':
        is_ordinal = True
        start_idx = i + 1
    run = _num_run_len(text, start_idx)
    if run == 0: return None
    base_end = start_idx + run
    for take in range(3, -1, -1):
        if base_end + take > n: continue
        span = text[i:base_end + take]
        r = patched_read_number_span(span)
        if r is not None: return (len(span), r)
    return None

def patched_read_number_span(han):
    if not han: return None
    han = han.strip()
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
                elif unit == '名': return f'hạng {v_num}'
                elif unit in ('天', '日'): return f'ngày thứ {v_num}'
                elif unit == '次': return f'lần thứ {v_num}'
                elif unit == '步': return f'bước thứ {v_num}'
                elif unit == '代': return f'đời thứ {v_num}'
        for table in (_CURRENCY, _TIME, _MEASURE):
            for unit in sorted(table, key=len, reverse=True):
                if rest.endswith(unit) and len(rest) > len(unit):
                    num_part = rest[:-len(unit)]
                    n = read_number(num_part)
                    if n is not None:
                        return f'{table[unit]} thứ {_fmt(n)}'
        n = read_number(rest)
        if n is not None: return f'thứ {_fmt(n)}'
        return None
    return read_number_span(han)

for t in ["第8章", "第一百零一回", "第三名", "第一个", "第五次", "第十"]:
    res = patched_match_at(t, 0)
    print(f"{t} -> {res}")
