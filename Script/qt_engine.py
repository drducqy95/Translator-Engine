#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translator Engine - QuickTranslator (QT) Core
Thực hiện dịch thô bằng giải thuật Quy hoạch động (Dynamic Programming)
kết hợp Đồ thị tri thức (Knowledge Base).
"""

import sqlite3
import functools
import re
from pathlib import Path

import numgrammar
import grammar
from tm_lookup import TMEngine

HV_OVERRIDES = {
    "释": "Thích",
}

# Bảng map dấu câu tiếng Trung -> tiếng Việt
PUNCT_MAP = {
    '，': ', ', '。': '. ', '！': '! ', '？': '? ', '、': ', ',
    '：': ': ', '；': '; ', '“': '"', '”': '"', '‘': "'", '’': "'",
    '（': ' (', '）': ') ', '《': '<', '》': '>', '【': '[', '】': ']'
}

def format_draft(text):
    # Thay thế dấu câu
    for k, v in PUNCT_MAP.items():
        text = text.replace(k, v)
    # Xoá khoảng trắng trước dấu câu
    text = re.sub(r'\s+([\,\.\!\?\:\;])', r'\1', text)
    # Đảm bảo có khoảng trắng sau dấu câu
    text = re.sub(r'([\,\.\!\?\:\;])(?=[^\s\"\'\)\>\]])', r'\1 ', text)
    # Xoá khoảng trắng sát sau ngoặc/trích dẫn mở
    text = re.sub(r'([\"\'\<\(\[])\s+', r'\1', text)
    # Xoá khoảng trắng sát trước ngoặc/trích dẫn đóng
    text = re.sub(r'\s+([\"\'\>\)\]])', r'\1', text)
    # Viết hoa đầu câu và đầu dòng (có thể bắt đầu bằng ngoặc kép/đơn)
    text = re.sub(r'(^[\"\']*\s*|[\.\!\?]\s*[\"\']*\s*)(\w)', lambda m: m.group(1) + m.group(2).upper(), text, flags=re.UNICODE | re.MULTILINE)
    
    # In nghiêng câu thoại (trong ngoặc kép)
    text = re.sub(r'\"\s*([^\"]+?)\s*\"', r'"*\1*"', text)
    
    return text.strip()

# Cấu hình DB
DB_PATH = Path('/sdcard/My Agent/Translator Engine/Dict/translator_knowledge.db')
_HAN = re.compile(r'[㐀-䶿一-鿿]')
# Các loại từ điển không dùng cho bản dịch tiếng Việt
EN_TYPES = ('cedict', 'babylon')

def is_han(ch):
    return bool(_HAN.match(ch))

class QTEngine:
    def __init__(self, db_path=DB_PATH, hot_cache=5000):
        # Nạp DictManager với kiến trúc đa tầng
        from dict_manager import DictManager
        self.db_path = Path(db_path)
        self.dict_mgr = DictManager(self.db_path.parent)
        try:
            self.dict_mgr.load_global(self.db_path.name)
        except Exception as exc:
            print(f"[QTEngine] load_global warning: {exc}")
        
        # Các dictionary proxy
        self.prefix = self.dict_mgr.prefix
        self.hanviet = self.dict_mgr.hanviet_dict
        self.hanviet.update(HV_OVERRIDES)
        self.t2s = self.dict_mgr.t2s
        
        try:
            self.tm_engine = TMEngine(self.db_path)
        except Exception as exc:
            print(f"[QTEngine] TMEngine warning: {exc}")
            self.tm_engine = None
        
        self.max_len = self.dict_mgr.max_len
        self.active_universes = []
        
        self.regex_num = re.compile(r'^[0-9零一二三四五六七八九十百千万亿]+$')
        self.regex_alpha = re.compile(r'^[a-zA-Z0-9]+$')

    def set_context(self, text: str):
        self.active_universes = self.dict_mgr.scan_active_universes(text)

    def _lookup(self, text):
        res = self.dict_mgr.lookup(text, self.active_universes)
        if not res: return None
        return self._clean(res)

    def _clean(self, r):
        tgt = (r[0] or '').strip()
        ttype = r[5] if len(r) > 5 else '' # source_dict
        
        # Dọn dẹp format của từ điển Lạc Việt
        if ttype == 'lacviet':
            tgt = re.sub(r'^[✚]+\s*\[[^\]]*\]\s*', '', tgt)
            parts = re.split(r'\\n|\n', tgt)
            gloss = ''
            for p in parts:
                p = re.sub(r'^(?:\\t|\t|\s)+', '', p).strip()
                m = re.match(r'^\d+\.\s*(.+)$', p)
                if m:
                    gloss = m.group(1).strip()
                    break
            if not gloss:
                head = re.sub(r'^(?:Hán Việt)\s*:\s*', '', parts[0]).strip()
                gloss = head
            tgt = gloss

        if tgt.startswith('/'):
            # Từ bỏ qua (thường là hư từ như 的, 地...)
            return ('', r[1], r[2], r[3], r[4])
            
        if '/' in tgt:
            cands = [c.strip() for c in tgt.split('/') if c.strip()]
            if cands:
                tgt = cands[0]
                
        # Dọn dẹp số thứ tự hoặc các giải nghĩa thừa
        tgt = re.sub(r'^\d+\.\s*', '', tgt).strip()
        if ';' in tgt:
            tgt = tgt.split(';', 1)[0].strip() or tgt
            
        return (tgt, r[1], r[2], r[3], r[4])

    def _max_window(self, ch):
        return self.prefix.get(ch, 0)

    # Hệ số Cost cho Dynamic Programming
    _C_DICT = 1.0   # Cost cho 1 ký tự map được với từ điển
    _C_HV = 4.0     # Cost cho 1 ký tự chỉ dịch được Hán Việt
    _C_UNK = 60.0   # Cost ký tự lạ
    _C_TOK = 0.05   # Penalty mỗi token (ưu tiên nối dài token)

    def translate(self, text, project_scope=None):
        known_entities = []
        if self.t2s:
            text = ''.join(self.t2s.get(c, c) for c in text)
            
        # Fast path: Translation Memory Lookup
        tm_match = self.tm_engine.lookup(text, project_scope)
        if tm_match:
            return tm_match, 1.0, [], []
            
        n = len(text)
        if n == 0:
            return '', 1.0, [], []

        INF = float('inf')
        dp = [0.0] * (n + 1)
        choice = [None] * (n + 1)

        for i in range(n - 1, -1, -1):
            ch = text[i]

            if not is_han(ch):
                dp[i] = self._C_TOK * 0.0 + dp[i + 1]
                choice[i] = (1, 'pass', ch, None, None)
                continue

            best_cost = INF
            best_choice = None
            
            num_match = numgrammar.match_at(text, i)
            if num_match:
                length, rendered = num_match
                # Đếm số ký tự Hán trong đoạn match để tính cost công bằng
                han_count = sum(1 for c in text[i:i+length] if is_han(c))
                cost = (self._C_DICT * han_count) + self._C_TOK + dp[i + length]
                if cost < best_cost:
                    best_cost = cost
                    best_choice = (length, 'num', rendered, None, None)

            window = self._max_window(ch)
            if window:
                hi = min(window, n - i)
                for length in range(hi, 0, -1):
                    res = self._lookup(text[i:i + length])
                    if not res:
                        continue
                    target, ttype, pos, tier, priority = res
                    han_in = sum(1 for c in text[i:i + length] if is_han(c))
                    cost = (self._C_DICT * han_in + self._C_TOK - 0.3 * tier + 0.002 * priority + dp[i + length])
                    if cost < best_cost:
                        best_cost = cost
                        best_choice = (length, 'dict', target, pos, ttype)

            hv = self.hanviet.get(ch)
            if hv is not None:
                cost = self._C_HV + self._C_TOK + dp[i + 1]
                if cost < best_cost:
                    best_cost = cost
                    best_choice = (1, 'hv', hv, None, None)

            cost = self._C_UNK + self._C_TOK + dp[i + 1]
            if cost < best_cost:
                best_cost = cost
                best_choice = (1, 'unk', ch, None, None)

            dp[i] = best_cost
            choice[i] = best_choice

        # Xây dựng văn bản đích dưới dạng token stream
        tokens = []
        unknown = []
        cur_unknown = []
        total_han = 0
        matched_han = 0

        def flush_unknown():
            if cur_unknown:
                src_str = ''.join(c[0] for c in cur_unknown)
                tgt_str = ''.join(c[1] for c in cur_unknown)
                tokens.append({'src': src_str, 'tgt': tgt_str, 'pos': None, 'kind': 'unk'})
                unknown.append({'raw': src_str, 'target': tgt_str})
                cur_unknown.clear()

        i = 0
        while i < n:
            choice_data = choice[i]
            if len(choice_data) == 5:
                length, kind, payload, pos, ttype = choice_data
            elif len(choice_data) == 4:
                length, kind, payload, pos = choice_data
                ttype = None
            else:
                length, kind, payload = choice_data
                pos = None
                ttype = None
                
            if ttype == 'name' and isinstance(payload, str):
                payload = payload.title()
                
            seg = text[i:i + length]
            han_in = sum(1 for c in seg if is_han(c))
            total_han += han_in

            if kind == 'pass':
                flush_unknown()
                tokens.append({'src': seg, 'tgt': payload, 'pos': None, 'kind': 'pass'})
            elif kind == 'dict':
                flush_unknown()
                tokens.append({'src': seg, 'tgt': payload, 'pos': pos, 'kind': 'dict', 'type': ttype})
                matched_han += han_in
            elif kind == 'num':
                flush_unknown()
                tokens.append({'src': seg, 'tgt': payload, 'pos': None, 'kind': 'num'})
                matched_han += han_in
            elif kind == 'hv':
                flush_unknown()
                tokens.append({'src': seg, 'tgt': payload, 'pos': None, 'kind': 'hv'})
                matched_han += 1
            else:
                cur_unknown.append((seg, payload))
                
            i += length
            
        flush_unknown()
        
        flush_unknown()
        
        # 1. Trích xuất Entity thô bằng jieba_env và làm sạch
        try:
            from jieba_env import get_char_pos_map, clean_entity, init_jieba
            import jieba.posseg as pseg
            
            init_jieba()
            
            # Enrich tokens POS
            pure_text = ''.join(c['src'] for c in tokens if c['kind'] != 'pass')
            if pure_text:
                char_tags = get_char_pos_map(pure_text)
                c_idx = 0
                for t in tokens:
                    if t['kind'] != 'pass' and t['src']:
                        tlen = len(t['src'])
                        if c_idx < len(char_tags):
                            # Gán POS tag của ký tự đầu tiên trong token
                            t['pos'] = char_tags[c_idx] 
                        c_idx += tlen
            
            # Trích xuất Entity (Unknown)
            for w, flag in pseg.cut(''.join(c['src'] for c in tokens if c['kind'] != 'pass')):
                if flag in ('nr', 'ns', 'nt', 'nz'):
                    cleaned_w = clean_entity(w, flag)
                    if len(cleaned_w) > 1:
                        res = self._lookup(cleaned_w)
                        if not res or res[0] is None:
                            tgt_chars = []
                            for char in cleaned_w:
                                res_char = self._lookup(char)
                                if res_char and res_char[0]:
                                    tgt_chars.append(res_char[0])
                                else:
                                    tgt_chars.append(char)
                                    
                            ent_dict = {'raw': cleaned_w, 'target': ' '.join(tgt_chars).title()}
                            
                            try:
                                from foreign_converter import analyze_and_convert_entity
                                f_ctx = analyze_and_convert_entity(cleaned_w)
                                if f_ctx:
                                    ent_dict['foreign_context'] = f_ctx
                            except Exception:
                                pass
                                
                            unknown.append(ent_dict)
                            
            # Trích xuất Entity (Known)
            for t in tokens:
                if t.get('type') in ('character', 'sect', 'location', 'item', 'name', 'entity', 'universe'):
                    known_entities.append({'raw': t['src'], 'target': t.get('tgt'), 'type': t.get('type')})
                    
        except Exception as e:
            print(f"[QTEngine] Jieba error: {e}")
            pass
            
        # Áp dụng chuỗi các quy tắc ngữ pháp (的/地, Location, Demonstratives)
        tokens = grammar.apply_grammar_pipeline(tokens, log=False)
        
        out = []
        prev_pass_alnum = False
        for tok in tokens:
            tgt = tok.get('tgt')
            if not tgt: continue
            
            if tok['kind'] == 'pass':
                if tgt.isalnum():
                    if prev_pass_alnum:
                        out.append(tgt)
                    else:
                        if out and not out[-1].isspace():
                            out.append(' ')
                        out.append(tgt)
                    prev_pass_alnum = True
                else:
                    if out and out[-1] == ' ' and not tgt[:1].isspace():
                        out.pop()
                    out.append(tgt)
                    prev_pass_alnum = False
            else:
                if out and not out[-1][-1:].isspace():
                    out.append(' ')
                out.append(tgt)
                prev_pass_alnum = False

        draft = format_draft(''.join(out))
        coverage = (matched_han / total_han) if total_han else 1.0
        return draft, round(coverage, 4), unknown, known_entities

    def close(self):
        try:
            if hasattr(self, 'dict_mgr'):
                self.dict_mgr.close()
        except Exception:
            pass

if __name__ == '__main__':
    qt = QTEngine()
    sample = "方元修炼灵气，召唤鹰爪手攻击老贼。"
    draft, cov, unk, known = qt.translate(sample)
    print("Source  :", sample)
    print("Draft   :", draft)
    print("Coverage:", cov)
    print("Unknown :", unk)
    print("Known   :", known)
    qt.close()
