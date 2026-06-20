import os
import sqlite3
import time

OLD_DB_PATH = "/sdcard/My Agent/Transbot/Data/transbot_dict.db"
NEW_DB_DIR = "/sdcard/My Agent/Translator Engine/Dict"
NEW_DB_PATH = os.path.join(NEW_DB_DIR, "translator_knowledge.db")

def migrate():
    print("=== BẮT ĐẦU NÂNG CẤP VÀ CHUYỂN ĐỔI DATABASE TRI THỨC ===")
    start_time = time.time()

    # 1. Đảm bảo thư mục đích tồn tại
    if not os.path.exists(NEW_DB_DIR):
        os.makedirs(NEW_DB_DIR)
        print(f"Đã tạo thư mục: {NEW_DB_DIR}")

    # 2. Xóa file database cũ nếu tồn tại để tránh xung đột dữ liệu cũ
    if os.path.exists(NEW_DB_PATH):
        os.remove(NEW_DB_PATH)
        print(f"Đã dọn dẹp file database mới cũ tại: {NEW_DB_PATH}")

    # 3. Kết nối với database mới
    conn = sqlite3.connect(NEW_DB_PATH)
    cursor = conn.cursor()

    # Tối ưu hiệu năng ghi chép SQLite
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = OFF;")
    cursor.execute("PRAGMA temp_store = MEMORY;")
    cursor.execute("PRAGMA cache_size = -100000;")  # Dành khoảng 100MB RAM làm cache ghi
    cursor.execute("PRAGMA foreign_keys = OFF;")

    try:
        # 4. Khởi tạo Schema mới
        print("Đang tạo các bảng dữ liệu mới...")
        
        # Bảng kb_node
        cursor.execute("""
        CREATE TABLE kb_node (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            tier INTEGER NOT NULL DEFAULT 0,
            scope TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)

        # Bảng kb_node_translation
        cursor.execute("""
        CREATE TABLE kb_node_translation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            vietnamese TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            priority INTEGER DEFAULT 100,
            pos TEXT,
            context_marker TEXT,
            source_dict TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(node_id) REFERENCES kb_node(id) ON DELETE CASCADE
        );
        """)

        # Bảng kb_node_attribute
        cursor.execute("""
        CREATE TABLE kb_node_attribute (
            node_id INTEGER NOT NULL,
            attr_key TEXT NOT NULL,
            attr_value TEXT NOT NULL,
            PRIMARY KEY (node_id, attr_key),
            FOREIGN KEY(node_id) REFERENCES kb_node(id) ON DELETE CASCADE
        );
        """)

        # Bảng kb_edge (Đồ thị quan hệ)
        cursor.execute("""
        CREATE TABLE kb_edge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(source_id) REFERENCES kb_node(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id) REFERENCES kb_node(id) ON DELETE CASCADE
        );
        """)

        # Bảng kb_edge_history
        cursor.execute("""
        CREATE TABLE kb_edge_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id INTEGER NOT NULL,
            chapter_index INTEGER NOT NULL,
            action TEXT NOT NULL,
            old_relation TEXT,
            new_relation TEXT,
            change_note TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(edge_id) REFERENCES kb_edge(id) ON DELETE CASCADE
        );
        """)

        # Bảng kb_translation_memory
        cursor.execute("""
        CREATE TABLE kb_translation_memory (
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

        # Bảng kb_grammar_rule
        cursor.execute("""
        CREATE TABLE kb_grammar_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            replacement TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            pos_trigger TEXT,
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)

        # Bảng kb_charmap
        cursor.execute("""
        CREATE TABLE kb_charmap (
            trad TEXT PRIMARY KEY,
            simp TEXT NOT NULL
        );
        """)

        # Bảng kb_hanviet_char
        cursor.execute("""
        CREATE TABLE kb_hanviet_char (
            han TEXT PRIMARY KEY,
            viet TEXT NOT NULL,
            pinyin TEXT
        );
        """)

        # Bảng kb_han_char
        cursor.execute("""
        CREATE TABLE kb_han_char (
            simp TEXT PRIMARY KEY,
            trad TEXT,
            hanviet TEXT,
            readings TEXT,
            pos_index TEXT,
            gloss_en TEXT,
            sources TEXT,
            confidence REAL DEFAULT 0.0
        );
        """)

        # Bảng kb_term_prefix (Hỗ trợ quét longest-match)
        cursor.execute("""
        CREATE TABLE kb_term_prefix (
            head TEXT PRIMARY KEY,
            max_len INTEGER NOT NULL
        );
        """)

        # Bảng kb_version & kb_changelog
        cursor.execute("""
        CREATE TABLE kb_version (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
        cursor.execute("""
        CREATE TABLE kb_changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            data_before TEXT,
            data_after TEXT,
            FOREIGN KEY(version_id) REFERENCES kb_version(version_id) ON DELETE CASCADE
        );
        """)

        # 5. Đính kèm database cũ để truy vấn liên kết
        print(f"Đang đính kèm database Transbot cũ từ: {OLD_DB_PATH}")
        cursor.execute(f"ATTACH DATABASE '{OLD_DB_PATH}' AS old_db;")

        # 6. Bắt đầu chuyển đổi dữ liệu
        print("Đang thực hiện chuyển đổi dữ liệu bằng SQL trực tiếp...")

        # 6.1 Chuyển các bảng 1-1
        print("-> Đang migrate charmap, hanviet_char, han_char, grammar_rule...")
        cursor.execute("INSERT INTO kb_charmap SELECT trad, simp FROM old_db.charmap;")
        cursor.execute("INSERT INTO kb_hanviet_char SELECT han, viet, pinyin FROM old_db.hanviet_char;")
        cursor.execute("INSERT INTO kb_han_char SELECT simp, trad, hanviet, readings, pos_index, gloss_en, sources, confidence FROM old_db.han_char;")
        cursor.execute("""
            INSERT INTO kb_grammar_rule (id, pattern, replacement, rule_type, pos_trigger, priority, enabled)
            SELECT id, pattern, replacement, rule_type, pos_trigger, priority, enabled FROM old_db.grammar_rule;
        """)

        # 6.2 Tạo Nodes (kb_node)
        print("-> Đang gom nhóm và tạo các Node tri thức từ bảng term cũ...")
        # Tạo node từ term (chỉ lấy key duy nhất)
        cursor.execute("""
            INSERT OR IGNORE INTO kb_node (key, type, tier, scope)
            SELECT DISTINCT source, 'term', tier, scope FROM old_db.term;
        """)

        # Cập nhật hoặc chèn thêm node từ entity (các thực thể đặc thù)
        print("-> Đang tích hợp thực thể từ bảng entity cũ...")
        # Chèn các node từ entity chưa có vào kb_node
        cursor.execute("""
            INSERT OR IGNORE INTO kb_node (key, type, tier, scope)
            SELECT DISTINCT source, 
                   CASE 
                       WHEN entity_type = 'person' THEN 'character'
                       WHEN entity_type = 'organization' THEN 'sect'
                       ELSE COALESCE(entity_type, 'term')
                   END, 
                   tier, scope 
            FROM old_db.entity;
        """)
        # Cập nhật lại type của các node đã có nếu chúng được khai báo trong entity
        cursor.execute("""
            UPDATE kb_node
            SET type = (
                SELECT CASE 
                           WHEN e.entity_type = 'person' THEN 'character'
                           WHEN e.entity_type = 'organization' THEN 'sect'
                           ELSE COALESCE(e.entity_type, 'term')
                       END
                FROM old_db.entity e
                WHERE e.source = kb_node.key
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM old_db.entity e WHERE e.source = kb_node.key
            );
        """)

        # 6.3 Tạo Node Translations (kb_node_translation)
        print("-> Đang chuyển bản dịch các từ vựng vào kb_node_translation...")
        cursor.execute("""
            INSERT INTO kb_node_translation (node_id, vietnamese, confidence, priority, pos, context_marker, source_dict)
            SELECT n.id, t.target, t.confidence, t.priority, t.pos, t.context_marker, t.type
            FROM old_db.term t
            JOIN kb_node n ON t.source = n.key;
        """)

        # 6.4 Tạo Node Attributes (kb_node_attribute)
        print("-> Đang cập nhật thuộc tính bổ sung của thực thể...")
        # Aliases
        cursor.execute("""
            INSERT OR IGNORE INTO kb_node_attribute (node_id, attr_key, attr_value)
            SELECT n.id, 'aliases', e.aliases
            FROM old_db.entity e
            JOIN kb_node n ON e.source = n.key
            WHERE e.aliases IS NOT NULL AND e.aliases != '' AND e.aliases != '[]';
        """)
        # Description
        cursor.execute("""
            INSERT OR IGNORE INTO kb_node_attribute (node_id, attr_key, attr_value)
            SELECT n.id, 'description', e.description
            FROM old_db.entity e
            JOIN kb_node n ON e.source = n.key
            WHERE e.description IS NOT NULL AND e.description != '';
        """)
        # Status
        cursor.execute("""
            INSERT OR IGNORE INTO kb_node_attribute (node_id, attr_key, attr_value)
            SELECT n.id, 'status', e.status
            FROM old_db.entity e
            JOIN kb_node n ON e.source = n.key
            WHERE e.status IS NOT NULL AND e.status != '';
        """)

        # 6.5 Tạo Edges (kb_edge) từ entity_edge cũ
        print("-> Đang thiết lập các liên kết mối quan hệ thực thể (kb_edge)...")
        cursor.execute("""
            INSERT INTO kb_edge (source_id, target_id, relationship, confidence)
            SELECT n_from.id, n_to.id, ee.relation, COALESCE(ee.weight, 1.0)
            FROM old_db.entity_edge ee
            JOIN old_db.entity e_from ON ee.from_id = e_from.id
            JOIN old_db.entity e_to ON ee.to_id = e_to.id
            JOIN kb_node n_from ON e_from.source = n_from.key
            JOIN kb_node n_to ON e_to.source = n_to.key;
        """)

        # 6.6 Chuyển đổi context_segment sang kb_translation_memory
        print("-> Đang đồng bộ bộ nhớ dịch thuật (kb_translation_memory)...")
        cursor.execute("""
            INSERT OR IGNORE INTO kb_translation_memory (raw_hash, raw_text, translated_text, confidence, project_scope, chapter_index, reviewed, created_at)
            SELECT source_hash, source, target, confidence, branch, chapter, reviewed, COALESCE(created_at, datetime('now', 'localtime'))
            FROM old_db.context_segment;
        """)

        # 6.7 Tạo kb_term_prefix để hỗ trợ quét longest-match
        print("-> Đang khởi tạo bộ tiền tố quét từ vựng (kb_term_prefix)...")
        cursor.execute("""
            INSERT INTO kb_term_prefix (head, max_len)
            SELECT substr(key, 1, 1) as head, max(length(key)) as max_len
            FROM kb_node
            GROUP BY head;
        """)

        # 7. Xây dựng các Index để tối ưu truy vấn
        print("Đang xây dựng các chỉ mục tối ưu truy vấn (Index)...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_key ON kb_node(key);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_type ON kb_node(type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_trans_id ON kb_node_translation(node_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_trans_val ON kb_node_translation(vietnamese);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edge_source ON kb_edge(source_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edge_target ON kb_edge(target_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tm_hash ON kb_translation_memory(raw_hash);")

        # 8. Commit Giao dịch và Detach db cũ
        conn.commit()
        cursor.execute("DETACH DATABASE old_db;")
        print("Chuyển đổi dữ liệu hoàn tất thành công!")

    except Exception as e:
        conn.rollback()
        print(f"[LỖI] Đã xảy ra lỗi trong quá trình chuyển đổi: {e}")
        raise e
    finally:
        conn.close()

    end_time = time.time()
    elapsed = end_time - start_time
    print(f"=== HOÀN THÀNH SAU {elapsed:.2f} GIÂY ===")

if __name__ == "__main__":
    migrate()
