import sqlite3
from pathlib import Path

class KnowledgeValidator:
    def __init__(self, novel_id: str, db_path=None):
        self.novel_id = novel_id
        if db_path is None:
            self.db_path = Path(__file__).parent.parent / "Dict" / f"project_{novel_id}.db"
        else:
            self.db_path = Path(db_path)
            
    def auto_validate(self, threshold=3.0):
        """Duyệt tự động các candidate có score >= threshold"""
        if not self.db_path.exists():
            return []
            
        approved = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            # Lấy các candidate đạt yêu cầu
            cur.execute("SELECT id, raw, target, type FROM candidate_entities WHERE status='pending' AND score >= ?", (threshold,))
            candidates = cur.fetchall()
            
            for cid, raw, target, etype in candidates:
                # Insert vào bảng chính thức
                try:
                    cur.execute("INSERT INTO dict_entries (key, target, type) VALUES (?, ?, ?)", (raw, target, etype))
                    cur.execute("UPDATE candidate_entities SET status='approved' WHERE id=?", (cid,))
                    approved.append({"raw": raw, "target": target, "type": etype})
                except sqlite3.IntegrityError:
                    # Duplicate in dict_entries
                    cur.execute("UPDATE candidate_entities SET status='rejected' WHERE id=?", (cid,))
            conn.commit()
            
        return approved
