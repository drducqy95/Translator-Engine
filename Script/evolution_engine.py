import sqlite3
import difflib
from pathlib import Path

class EvolutionEngine:
    def __init__(self, novel_id: str, db_path=None):
        self.novel_id = novel_id
        if db_path is None:
            self.db_path = Path(__file__).parent.parent / "Dict" / f"project_{novel_id}.db"
        else:
            self.db_path = Path(db_path)

    def analyze_diff(self, qt_draft: str, ai_final: str):
        """So sánh Draft và Final để phát hiện các mẫu sửa lỗi lặp lại"""
        matcher = difflib.SequenceMatcher(None, qt_draft.split(), ai_final.split())
        patterns = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'replace':
                qt_segment = ' '.join(qt_draft.split()[i1:i2])
                ai_segment = ' '.join(ai_final.split()[j1:j2])
                
                # Bỏ qua các thay đổi quá dài (thường là viết lại nguyên câu)
                if len(qt_segment) < 30 and len(ai_segment) < 30:
                    patterns.append({
                        "original": qt_segment,
                        "refined": ai_segment,
                        "type": "grammar_or_style"
                    })
        return patterns

    def run_batch_evolution(self, chapter_limit=50):
        """Chạy batch analysis để trích xuất luật"""
        # Pseudo-code cho evolution batch:
        # 1. Lấy lịch sử TM của 50 chương gần nhất
        # 2. Chạy analyze_diff cho từng cặp
        # 3. Gom nhóm và đếm tần suất các cặp (original, refined)
        # 4. Nếu tần suất > threshold, tự động sinh grammar rule mới
        print(f"[Evolution Engine] Đang phân tích mẫu dịch cho {self.novel_id} (Limit: {chapter_limit})")
        return True
