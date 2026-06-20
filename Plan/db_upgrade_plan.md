# KẾ HOẠCH NÂNG CẤP VÀ CHUYỂN ĐỔI DATABASE TRI THỨC (KNOWLEDGE BASE)

Tài liệu này chi tiết hóa cấu trúc cơ sở dữ liệu SQLite mới cho **Translator Engine** và kế hoạch chuyển đổi (migration) dữ liệu từ `transbot_dict.db` (dự án Transbot cũ) sang hệ thống đồ thị tri thức mới.

---

## I. THIẾT KẾ SCHEMA SQLITE MỚI (`translator_knowledge.db`)

Hệ thống lưu trữ mới chuyển dịch từ cấu trúc "từ điển phẳng" sang "đồ thị tri thức liên kết", tách biệt thực thể (Node), bản dịch (Translation), thuộc tính (Attribute) và mối quan hệ (Edge).

### 1. Bảng Core & Đồ thị thực thể

#### Bảng `kb_node` (Các nút tri thức: từ vựng, nhân vật, địa danh...)
```sql
CREATE TABLE IF NOT EXISTS kb_node (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,             -- Từ gốc tiếng Trung (e.g., '元婴', '王默')
    type TEXT NOT NULL,                   -- Loại node: term, character, location, item, title, sect, boundary, grammar, style
    tier INTEGER NOT NULL DEFAULT 0,      -- 0: global, 1: universe, 2: project
    scope TEXT,                           -- NULL (global), universe_id, hoặc project_slug
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_node_key ON kb_node(key);
CREATE INDEX IF NOT EXISTS idx_node_type ON kb_node(type);
```

#### Bảng `kb_node_translation` (Danh sách các nghĩa dịch tiếng Việt tương ứng)
```sql
CREATE TABLE IF NOT EXISTS kb_node_translation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    vietnamese TEXT NOT NULL,             -- Bản dịch nghĩa Việt
    confidence REAL DEFAULT 1.0,          -- Độ tin cậy (0.0 -> 1.0)
    priority INTEGER DEFAULT 100,         -- Thứ tự ưu tiên (số nhỏ ưu tiên cao hơn)
    pos TEXT,                             -- Từ loại (noun, verb, adj...)
    context_marker TEXT,                  -- Ngữ cảnh áp dụng bản dịch này (NULL = universal)
    source_dict TEXT,                     -- Nguồn gốc (VietPhrase, AI_learned, manual...)
    is_active INTEGER DEFAULT 1,          -- 1: Hoạt động, 0: Bị tắt
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(node_id) REFERENCES kb_node(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_node_trans_id ON kb_node_translation(node_id);
```

#### Bảng `kb_node_attribute` (Lưu trữ các thuộc tính linh hoạt - mô hình EAV)
```sql
CREATE TABLE IF NOT EXISTS kb_node_attribute (
    node_id INTEGER NOT NULL,
    attr_key TEXT NOT NULL,               -- e.g., 'gender', 'cultivation_rank', 'description', 'aliases'
    attr_value TEXT NOT NULL,             -- Lưu giá trị phẳng hoặc chuỗi JSON
    PRIMARY KEY (node_id, attr_key),
    FOREIGN KEY(node_id) REFERENCES kb_node(id) ON DELETE CASCADE
);
```

### 2. Đồ thị mối quan hệ (Relationship Graph)

#### Bảng `kb_edge` (Mối quan hệ giữa các thực thể)
```sql
CREATE TABLE IF NOT EXISTS kb_edge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    relationship TEXT NOT NULL,           -- Loại quan hệ (master_of, spouse_of, enemy_of, part_of...)
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(source_id) REFERENCES kb_node(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES kb_node(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edge_source ON kb_edge(source_id);
CREATE INDEX IF NOT EXISTS idx_edge_target ON kb_edge(target_id);
```

#### Bảng `kb_edge_history` (Lịch sử biến đổi quan hệ theo diễn biến cốt truyện)
```sql
CREATE TABLE IF NOT EXISTS kb_edge_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id INTEGER NOT NULL,
    chapter_index INTEGER NOT NULL,       -- Chương xảy ra sự biến đổi quan hệ
    action TEXT NOT NULL,                 -- 'create', 'update', 'delete'
    old_relation TEXT,
    new_relation TEXT,
    change_note TEXT,                     -- Ghi chú lý do thay đổi quan hệ
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(edge_id) REFERENCES kb_edge(id) ON DELETE CASCADE
);
```

### 3. Bộ nhớ dịch thuật & Ngữ pháp

#### Bảng `kb_translation_memory` (Tái sử dụng câu/đoạn đã dịch chuẩn)
```sql
CREATE TABLE IF NOT EXISTS kb_translation_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_hash TEXT UNIQUE NOT NULL,        -- MD5 hash của câu gốc để tìm kiếm nhanh
    raw_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    hit_count INTEGER DEFAULT 1,
    confidence REAL DEFAULT 1.0,
    project_scope TEXT,                   -- Giới hạn phạm vi truyện (NULL = global)
    chapter_index INTEGER,
    reviewed INTEGER DEFAULT 0,           -- 1: Đã duyệt thủ công, 0: AI tự học chưa duyệt
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    last_used_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tm_hash ON kb_translation_memory(raw_hash);
```

#### Bảng `kb_grammar_rule` (Quy tắc chuyển đổi ngữ pháp)
```sql
CREATE TABLE IF NOT EXISTS kb_grammar_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    replacement TEXT NOT NULL,
    rule_type TEXT NOT NULL,              -- 'luatnhan_template', 'reorder', 'measure_word'
    pos_trigger TEXT,
    priority INTEGER DEFAULT 100,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
```

### 4. Từ điển nền tảng (Bản đồ Hán Việt & Tra tự)

#### Bảng `kb_charmap` (Bản đồ Phồn -> Giản)
```sql
CREATE TABLE IF NOT EXISTS kb_charmap (
    trad TEXT PRIMARY KEY,
    simp TEXT NOT NULL
);
```

#### Bảng `kb_hanviet_char` (Phiên âm Hán-Việt đơn âm tốc độ cao)
```sql
CREATE TABLE IF NOT EXISTS kb_hanviet_char (
    han TEXT PRIMARY KEY,
    viet TEXT NOT NULL,
    pinyin TEXT
);
```

#### Bảng `kb_han_char` (Từ điển Hán tự đa chiều chi tiết)
```sql
CREATE TABLE IF NOT EXISTS kb_han_char (
    simp TEXT PRIMARY KEY,
    trad TEXT,
    hanviet TEXT,
    readings TEXT,                        -- JSON: [{pinyin,hanviet,latin,senses[]}]
    pos_index TEXT,                       -- JSON set các loại từ
    gloss_en TEXT,
    sources TEXT,                         -- JSON nguồn gốc ['tc','lv','cd'...]
    confidence REAL DEFAULT 0.0
);
```

### 5. Quản lý phiên bản tri thức (Versioning & Undo)

```sql
CREATE TABLE IF NOT EXISTS kb_version (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS kb_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL,                 -- 'INSERT', 'UPDATE', 'DELETE'
    data_before TEXT,                     -- Dữ liệu cũ dạng JSON
    data_after TEXT,                      -- Dữ liệu mới dạng JSON
    FOREIGN KEY(version_id) REFERENCES kb_version(version_id) ON DELETE CASCADE
);
```

---

## II. KẾ HOẠCH CHUYỂN ĐỔI DỮ LIỆU (MIGRATION PLAN)

### 1. Nguồn dữ liệu cũ (`transbot_dict.db`)
*   Đường dẫn nguồn: `/sdcard/My Agent/Transbot/Data/transbot_dict.db`
*   Dung lượng: ~165MB (chứa hàng triệu từ khóa và dữ liệu Hán tự nền tảng).

### 2. Quy tắc ánh xạ dữ liệu (Mapping Rules)

*   **Từ `term` cũ sang `kb_node` và `kb_node_translation`**:
    *   Mỗi `term` độc nhất theo `source` (chữ Hán) sẽ tạo ra một `kb_node`.
    *   `kb_node.key` = `term.source`.
    *   `kb_node.type` = Nếu `term.type` thuộc nhóm `('name', 'cedict', 'manual', 'vietphrase')` và có thông tin loại thực thể ở bảng `entity` thì cập nhật đúng loại thực thể. Mặc định là `'term'`.
    *   Tạo bản ghi tương ứng trong `kb_node_translation` với các thông tin: `vietnamese = term.target`, `confidence = term.confidence`, `priority = term.priority`, `pos = term.pos`, `context_marker = term.context_marker`, `source_dict = term.source_dict`, `is_active = 1`.
    *   Nếu có nhiều bản dịch cho một từ gốc, chúng sẽ được gom chung dưới một `node_id` nhưng là các dòng khác nhau trong bảng `kb_node_translation`.

*   **Từ `entity` cũ sang `kb_node` & `kb_node_attribute`**:
    *   Do bảng `entity` của Transbot chứa thông tin chi tiết về thực thể, ta sẽ ánh xạ `entity.source` vào `kb_node.key`.
    *   Nếu node đã được tạo từ bước xử lý `term` trước đó, ta chỉ cập nhật `kb_node.type` từ `term` thành loại thực thể phù hợp (`character`, `location`, `item`...).
    *   Đồng thời thêm các thuộc tính mở rộng (như mô tả `description`, bí danh `aliases`, mốc xuất hiện `first_seen`, `last_seen`) vào bảng `kb_node_attribute`.

*   **Từ `entity_edge` cũ sang `kb_edge`**:
    *   Mỗi liên kết thực thể `from_id -> to_id` sẽ được chuyển sang `kb_edge` bằng cách tra cứu ID của node nguồn và đích tương ứng trong bảng `kb_node` mới.
    *   `relationship` = `entity_edge.relation`, `confidence` = `entity_edge.weight`.

*   **Từ `context_segment` cũ sang `kb_translation_memory`**:
    *   Ánh xạ trực tiếp sang `kb_translation_memory`.
    *   `raw_hash` = `context_segment.source_hash`, `raw_text` = `context_segment.source`, `translated_text` = `context_segment.target`, `project_scope` = `context_segment.branch`, `reviewed` = `context_segment.reviewed`.

*   **Từ các bảng nền tảng (charmap, hanviet_char, han_char, grammar_rule)**:
    *   Ánh xạ trực tiếp 1-1 sang các bảng `kb_charmap`, `kb_hanviet_char`, `kb_han_char`, `kb_grammar_rule`.

### 3. Tối ưu hóa hiệu năng Migration
Vì cơ sở dữ liệu gốc rất lớn (~165MB, hàng trăm nghìn bản ghi), script chuyển đổi cần tuân thủ:
*   Chạy trong một giao dịch duy nhất (`BEGIN TRANSACTION; ... COMMIT;`).
*   Sử dụng bộ nhớ cache tạm thời để lưu bản đồ ánh xạ ID của Node cũ -> Node mới nhằm tăng tốc ghi `kb_edge`.
*   Tạo toàn bộ INDEX sau khi đã nạp dữ liệu xong (chứ không tạo trước) để giảm thời gian chèn dữ liệu.
*   Sử dụng các câu lệnh chèn hàng loạt (`executemany` trong Python).
