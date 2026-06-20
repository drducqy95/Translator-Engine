#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grammar transforms for the QuickTranslator draft (shared by translator + pipeline).

Operates on a TOKEN STREAM (not raw text) so it can see neighbours and reorder:
    token = {'src': '<han span>', 'tgt': '<viet|''>', 'pos': set()|None, 'kind': str}

Two transforms, both conservative + logged so an aggressive reorder can be audited:

  1. de_particle  — 的 / 地 between two phrases. Decision by neighbour POS:
       A=pronoun/name  -> possessive:  B của A      (我的主人 -> chủ nhân của ta)
       head=verb       -> adverbial:   drop 的, keep order (不停的爆发 -> không ngừng bùng phát)
       A=adj, head=noun-> modifier:    B A (drop 的, swap)  (巨大的力量 -> lực lượng to lớn)
       的 at clause end -> keep dropped, no swap (好好的)
  2. luatnhan      — affix templates ({0}军团 -> quân đoàn {0}) matched on the SOURCE span.

Every reorder appends a line to Data/grammar_reorder_log.txt (span + before/after) so the
aggressive policy stays auditable.
"""
import re
from pathlib import Path

from pathlib import Path
import sqlite3

ROOT = Path('/sdcard/My Agent/Translator Engine')
REORDER_LOG = ROOT / 'Temp' / 'grammar_reorder_log.txt'
DB_PATH = ROOT / 'Dict' / 'translator_knowledge.db'

db_rules_cache = None

def load_db_rules():
    global db_rules_cache
    if db_rules_cache is not None:
        return db_rules_cache
    
    db_rules_cache = []
    if not DB_PATH.exists():
        return db_rules_cache
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT pattern, replacement, rule_type, pos_trigger FROM kb_grammar_rule WHERE enabled=1 ORDER BY priority ASC")
            for row in cur.fetchall():
                db_rules_cache.append(dict(row))
    except Exception as e:
        pass
        
    return db_rules_cache

# Chinese personal pronouns (A in 'A 的 B' => possessive 'B của A').
PRONOUNS = {
    '我': 'ta', '你': 'ngươi', '他': 'hắn', '她': 'nàng', '它': 'nó',
    '我们': 'chúng ta', '你们': 'các ngươi', '他们': 'bọn họ', '她们': 'bọn nàng',
    '咱': 'ta', '咱们': 'chúng ta', '自己': 'mình', '人家': 'người ta',
}

DE = {'的', '地'}


def _log_reorder(kind, before, after):
    try:
        with open(REORDER_LOG, 'a', encoding='utf-8') as f:
            f.write(f'{kind}\t{before}\t->\t{after}\n')
    except Exception:
        pass


def _is_content(tok):
    """A token that carries Vietnamese output (not a dropped particle / empty)."""
    return bool((tok.get('tgt') or '').strip())


def _has_pos(tok, pos_of, want):
    """True if the token's pos field contains want."""
    pos_str = tok.get('pos')
    if not pos_str:
        return False
    pos_list = [p.strip() for p in pos_str.split(',')]
    # Hỗ trợ Jieba POS tags: Các tag bắt đầu bằng want (vd: 'nr', 'ns' chứa 'n'; 'vd', 'vn' chứa 'v')
    for p in pos_list:
        if p == want or p.startswith(want):
            return True
    return False


def apply_grammar_pipeline(tokens, log=False):
    """Run all grammar passes in sequence."""
    tokens = apply_de(tokens, log=log)
    tokens = apply_location(tokens)
    tokens = apply_demonstrative(tokens)
    tokens = apply_db_rules(tokens)
    return tokens

def apply_db_rules(tokens):
    rules = load_db_rules()
    if not rules:
        return tokens
        
    # Apply simple replace rules for now
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        src = (tok.get('src') or '').strip()
        matched = False
        
        for r in rules:
            if r['rule_type'] == 'replace' and r['pattern'] == src:
                # Basic literal replace
                tok['tgt'] = r['replacement']
                break
                
        out.append(tok)
        i += 1
        
    return out

def apply_de(tokens, pos_of=None, log=True):
    """Reorder around 的/地 particles. Returns a new token list.
    tokens: list of {'src','tgt','pos','kind'}. pos_of: char -> set(pos) or None."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        src = (tok.get('src') or '').strip()
        # A 的/地 particle is a dict token whose source is exactly 的/地 (target dropped to '').
        if src in DE and not _is_content(tok):
            prev = out[-1] if out else None
            nxt = None
            j = i + 1
            while j < n:
                if _is_content(tokens[j]):
                    nxt = tokens[j]
                    break
                j += 1
            # Need both a left phrase (prev) and a right head (nxt) to reorder.
            # The head must be a real Vietnamese word (starts with a letter) — never a
            # punctuation/bracket token like 《, which must not be dragged into a reorder.
            nhead = (nxt.get('tgt') or '').strip() if nxt else ''
            head_is_word = bool(nhead) and nhead[0].isalpha()
            if prev is not None and nxt is not None and _is_content(prev) and head_is_word:
                psrc = (prev.get('src') or '').strip()
                # 1) possessive: A is a PRONOUN only. POS-'name' from cedict 'surname X'
                # is far too broad (most chars carry it) and turned verbs/adjectives into
                # bogus 'của' reorders, so possessive is gated on the closed pronoun set.
                if psrc in PRONOUNS:
                    a = out.pop()
                    before = f"{a['tgt']} {src} {nxt['tgt']}"
                    out.append(dict(nxt))
                    out.append({'src': '', 'tgt': 'của', 'pos': None, 'kind': 'gram'})
                    out.append(dict(a))
                    if log:
                        _log_reorder('possessive', before,
                                     f"{nxt['tgt']} của {a['tgt']}")
                    # skip prev(already moved), particle, and consume nxt
                    i = j + 1
                    continue
                # 2) adverbial: head is a verb -> drop 的, keep order (no swap)
                if _has_pos(nxt, pos_of, 'v') and not _has_pos(nxt, pos_of, 'n'):
                    # current behaviour already drops the particle; just continue
                    i += 1
                    continue
                # 3) modifier-head: A is adjective, head is noun -> 'B A' (swap, drop 的)
                if _has_pos(prev, pos_of, 'adj') and _has_pos(nxt, pos_of, 'n'):
                    a = out.pop()
                    before = f"{a['tgt']} {src} {nxt['tgt']}"
                    out.append(dict(nxt))
                    out.append(dict(a))
                    if log:
                        _log_reorder('modifier', before, f"{nxt['tgt']} {a['tgt']}")
                    i = j + 1
                    continue
            # default: drop the particle (keep order) — current behaviour
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def compile_luatnhan(rows):
    """rows: iterable of (pattern, replacement) with a single {0} slot.
    Returns list of (compiled_regex, replacement_template, orientation)."""
    compiled = []
    for pat, repl in rows:
        if '{0}' not in pat:
            continue
        lit = re.escape(pat).replace(re.escape('{0}'), r'(.+?)')
        try:
            rx = re.compile('^' + lit + '$')
        except re.error:
            continue
        # orientation: where {0} sits in the SOURCE pattern
        idx = pat.index('{0}')
        orient = 'pre' if idx == 0 else ('post' if idx == len(pat) - 3 else 'mid')
        compiled.append((rx, repl, orient))
    return compiled

LOCATIONS = {
    '上': 'trên', '下': 'dưới', '里': 'trong', '内': 'trong', 
    '外': 'ngoài', '前': 'trước', '后': 'sau', '中': 'trong',
    '之中': 'trong', '之上': 'trên', '之下': 'dưới', '之内': 'trong', '之外': 'ngoài'
}

def apply_location(tokens):
    """Invert [Noun] + [Location] -> [Location] + [Noun] (e.g., 电脑中 -> trong máy tính)"""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        src = (tok.get('src') or '').strip()
        if src in LOCATIONS and _is_content(tok):
            if out and _is_content(out[-1]):
                prev = out[-1]
                # Chỉ đảo nếu từ liền trước không phải là Động từ
                if not _has_pos(prev, None, 'v'):
                    loc_tok = dict(tok)
                    loc_tok['tgt'] = LOCATIONS[src]
                    p = out.pop()
                    out.append(loc_tok)
                    out.append(p)
                    i += 1
                    continue
        out.append(tok)
        i += 1
    return out

def apply_demonstrative(tokens):
    """Invert [Demonstrative] + [Noun] -> [Noun] + [Demonstrative] (e.g., 这个人 -> cái người này)"""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        src = (tok.get('src') or '').strip()
        
        if src in ('这', '那', '某', '这个', '那个') and _is_content(tok):
            nxt = None
            j = i + 1
            while j < n:
                if _is_content(tokens[j]):
                    nxt = tokens[j]
                    break
                j += 1
                
            if nxt:
                nsrc = (nxt.get('src') or '').strip()
                # Không đảo nếu phía sau là Động từ/Trợ từ phổ biến (VD: Đây là, Này thì...)
                if nsrc not in ('是', '在', '有', '就', '也', '才', '让', '被', '把', '将', '的', '地', '得'):
                    cls_viet, dem_viet = '', ''
                    if src == '这': dem_viet = 'này'
                    elif src == '那': dem_viet = 'kia'
                    elif src == '某': dem_viet = 'nào đó'
                    elif src == '这个': cls_viet, dem_viet = 'cái', 'này'
                    elif src == '那个': cls_viet, dem_viet = 'cái', 'kia'
                    
                    if cls_viet:
                        out.append({'src': '', 'tgt': cls_viet, 'pos': None, 'kind': 'gram'})
                    
                    out.append(dict(nxt))
                    out.append({'src': src, 'tgt': dem_viet, 'pos': None, 'kind': 'gram'})
                    
                    i = j + 1
                    continue
                    
        out.append(tok)
        i += 1
    return out
