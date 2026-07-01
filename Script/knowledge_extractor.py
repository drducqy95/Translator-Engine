import sqlite3
import re
from pathlib import Path

LATIN_RE = re.compile(r"[A-Za-z]")

class KnowledgeExtractor:
    def __init__(self, novel_id: str, db_path=None):
        self.novel_id = novel_id
        if db_path is None:
            self.db_path = Path(__file__).parent.parent / "Dict" / f"project_{novel_id}.db"
        else:
            self.db_path = Path(db_path)
            
        self._init_db()

    def _init_db(self):
        if not self.db_path.exists():
            return
        # Bảng phụ để lưu ứng viên trước khi duyệt
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS candidate_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw TEXT NOT NULL,
                target TEXT NOT NULL,
                type TEXT NOT NULL,
                score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            """)

    def process_new_entities(self, new_entities: list):
        if not self.db_path.exists() or not new_entities:
            return []
            
        added_candidates = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for ent in new_entities:
                raw = ent.get('raw', '').strip()
                target = ent.get('target', '').strip()
                etype = ent.get('type', 'unknown').strip()
                
                if not raw or not target:
                    continue
                    
                # Tra trùng trong bảng chính (dict_entries của project)
                cur.execute("SELECT target FROM dict_entries WHERE key=? AND type=?", (raw, etype))
                existing = cur.fetchone()
                if existing:
                    existing_target = existing[0] or ""
                    if LATIN_RE.search(existing_target) and not LATIN_RE.search(target):
                        continue
                    if existing_target == target:
                        continue
                    
                # Tra trùng trong candidate
                cur.execute("SELECT id FROM candidate_entities WHERE raw=? AND target=? AND type=?", (raw, target, etype))
                if cur.fetchone():
                    # Nếu đã có candidate giống hệt, tăng điểm score lên
                    cur.execute("UPDATE candidate_entities SET score = score + 1.0 WHERE raw=? AND target=? AND type=?", (raw, target, etype))
                    continue
                    
                # Thêm mới candidate
                cur.execute("INSERT INTO candidate_entities (raw, target, type, score) VALUES (?, ?, ?, ?)", (raw, target, etype, 1.0))
                added_candidates.append(ent)

                # Đồng bộ trực tiếp sang dict_entries để khóa target ổn định cho các chương sau.
                cur.execute(
                    "INSERT OR REPLACE INTO dict_entries (key, target, type) VALUES (?, ?, ?)",
                    (raw, target, etype),
                )
                
            conn.commit()
            
        return added_candidates
