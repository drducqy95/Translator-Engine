import sqlite3
from pathlib import Path

class RelationshipManager:
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_edge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relationship TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(source, target, relationship)
            );
            """)

    def save_relationships(self, relationships: list):
        if not self.db_path.exists() or not relationships:
            return
            
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for rel in relationships:
                source = rel.get('source', '').strip()
                target = rel.get('target', '').strip()
                relation = rel.get('relationship', '').strip()
                
                if not source or not target or not relation:
                    continue
                    
                try:
                    cur.execute("""
                    INSERT OR IGNORE INTO kb_edge (source, target, relationship) 
                    VALUES (?, ?, ?)
                    """, (source, target, relation))
                except Exception as e:
                    print(f"Rel Save Error: {e}")
            conn.commit()

    def get_context(self):
        """Trả về toàn bộ đồ thị quan hệ để nạp vào Context Pack"""
        if not self.db_path.exists():
            return []
            
        edges = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT source, target, relationship FROM kb_edge")
                for src, tgt, rel in cur.fetchall():
                    edges.append(f"{src} --({rel})--> {tgt}")
            except Exception:
                pass
        return edges
