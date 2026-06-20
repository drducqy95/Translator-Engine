#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translator Engine - Entity Scanner
Quét và phân loại thuật ngữ, tên riêng, thực thể, môn phái, cảnh giới...
để gửi AI hoặc đối chiếu với Knowledge Base.
"""

import sqlite3
import re
from pathlib import Path

DB_PATH = Path('/sdcard/My Agent/Translator Engine/Dict/translator_knowledge.db')

class EntityScanner:
    def __init__(self, project_scope=None, universe_scope=None, db_path=DB_PATH):
        self.project_scope = project_scope
        self.universes = set([universe_scope]) if isinstance(universe_scope, str) else set(universe_scope or [])
        self.ok = False
        try:
            if Path(db_path).exists():
                self.conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, check_same_thread=False)
                self.conn.execute('PRAGMA query_only = 1')
                self.conn.row_factory = sqlite3.Row
                self.ok = True
        except Exception:
            self.ok = False

    def check_entity_status(self, source):
        """
        Phân loại candidate dựa trên Knowledge Base.
        Trả về dictionary thuộc tính nếu tồn tại (đã biết), hoặc None nếu là từ mới.
        """
        if not self.ok:
            return None
            
        # Tìm trong db xem từ này là thực thể loại gì
        rows = self.conn.execute('''
            SELECT n.type, t.vietnamese, n.tier, n.scope
            FROM kb_node n
            JOIN kb_node_translation t ON n.id = t.node_id
            WHERE n.key = ? AND t.is_active = 1
            ORDER BY n.tier DESC, t.priority ASC LIMIT 5
        ''', (source,)).fetchall()
        
        if not rows:
            return None

        # Lọc theo scope
        for r in rows:
            sc = r['scope']
            if sc is None or (r['tier'] == 2 and sc == self.project_scope) or (r['tier'] == 1 and sc in self.universes):
                return {
                    'target': r['vietnamese'],
                    'type': r['type'] # character, sect, location, term, item...
                }
        
        return {
            'target': rows[0]['vietnamese'],
            'type': rows[0]['type']
        }

    def heuristic_scan(self, text):
        """
        Quét sơ bộ văn bản tiếng Trung để trích xuất các cụm ký tự có thể là Tên riêng.
        (Đây là logic cơ bản, có thể nâng cấp bằng jieba hoặc NER model)
        Thường dựa vào tần suất các ký tự không dịch được hoặc các hậu tố/tiền tố.
        """
        # Cắt các chuỗi Hán tự liên tiếp (độ dài 2-4) làm candidate
        # Hiện tại sẽ dùng RegExp để quét các mẫu xưng hô
        candidates = set()
        
        # Mẫu họ tên thường đi kèm từ xưng hô: "Lão [Họ]", "[Tên] sư huynh"
        # ... TODO: Thêm luật NLP nâng cao
        
        # Ví dụ tìm từ viết hoa (nếu text đã được gán nhãn, hoặc có dấu ngoặc kép)
        matches = re.findall(r'「([^」]+)」', text)
        for m in matches:
            if 1 < len(m) <= 5:
                candidates.add(m)
                
        return list(candidates)

    def classify_candidates(self, candidates):
        """
        Chia mảng các từ nghi ngờ thành:
        - known: Đã có trong Dict Graph
        - unknown: Chưa có, cần gửi cho AI Refiner để quyết định
        """
        known = {}
        unknown = []
        for src in candidates:
            hit = self.check_entity_status(src)
            if hit:
                # Nếu type là term chung chung, ta vẫn có thể muốn AI xem xét lại
                # Nhưng nếu type đã là character/sect thì ta đã biết.
                known[src] = hit
            else:
                unknown.append(src)
        return known, unknown

    def close(self):
        if self.ok and self.conn:
            self.conn.close()

if __name__ == '__main__':
    scanner = EntityScanner()
    candidates = ['方元', '鹰爪手', '老贼', '地球', 'KhôngBiết']
    known, unknown = scanner.classify_candidates(candidates)
    import json
    print("Known  :", json.dumps(known, ensure_ascii=False, indent=2))
    print("Unknown:", unknown)
    scanner.close()
