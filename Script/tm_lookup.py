import sqlite3
import hashlib
from pathlib import Path

class TMEngine:
    def __init__(self, db_path=None):
        if db_path is None:
            self.db_path = Path(__file__).parent.parent / "Dict" / "translator_knowledge.db"
        else:
            self.db_path = Path(db_path)
            
        self._init_db()

    def _init_db(self):
        if not self.db_path.exists():
            return
        # Ensure schema exists just in case (though it should be there)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_translation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_hash TEXT UNIQUE NOT NULL,
                raw_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                hit_count INTEGER DEFAULT 1,
                confidence REAL DEFAULT 1.0,
                project_scope TEXT,
                chapter_index INTEGER,
                reviewed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                last_used_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            """)

    def _hash(self, text):
        return hashlib.md5(text.strip().encode('utf-8')).hexdigest()

    def lookup(self, raw_text, project_scope=None):
        """Find exact match in TM"""
        if not self.db_path.exists():
            return None
            
        h = self._hash(raw_text)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            # Try to find exact match with project scope first
            if project_scope:
                cur.execute("SELECT translated_text FROM kb_translation_memory WHERE raw_hash=? AND project_scope=?", (h, project_scope))
                res = cur.fetchone()
                if res:
                    self._update_hit(conn, h)
                    return res['translated_text']
            
            # Fallback to global match
            cur.execute("SELECT translated_text FROM kb_translation_memory WHERE raw_hash=?", (h,))
            res = cur.fetchone()
            if res:
                self._update_hit(conn, h)
                return res['translated_text']
                
        return None

    def _update_hit(self, conn, raw_hash):
        conn.execute("UPDATE kb_translation_memory SET hit_count = hit_count + 1, last_used_at = datetime('now', 'localtime') WHERE raw_hash=?", (raw_hash,))
        conn.commit()

    def save(self, raw_text, translated_text, project_scope=None, chapter_index=None, confidence=1.0, reviewed=0):
        if not self.db_path.exists():
            return False
            
        h = self._hash(raw_text)
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                INSERT INTO kb_translation_memory 
                (raw_hash, raw_text, translated_text, project_scope, chapter_index, confidence, reviewed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_hash) DO UPDATE SET
                translated_text=excluded.translated_text,
                project_scope=excluded.project_scope,
                confidence=excluded.confidence,
                reviewed=excluded.reviewed,
                last_used_at=datetime('now', 'localtime')
                """, (h, raw_text.strip(), translated_text.strip(), project_scope, chapter_index, confidence, reviewed))
                return True
            except sqlite3.Error as e:
                print(f"TM Save Error: {e}")
                return False
