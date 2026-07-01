# KẾ HOẠCH TÍCH HỢP QT GRAPH CHO E-READER + TRANSLATOR ENGINE

Ngày: 2026-06-24
Phạm vi:

- `/sdcard/My Agent/e-reader`
- `/sdcard/My Agent/Translator Engine`

Mục tiêu: biến hệ thống thành nền tảng dịch realtime có cache, QT Graph, quản trị từ điển/character/glossary, provider settings, và pipeline dịch nội dung truyện có thể chọn **thuần QT Graph** hoặc **QT Graph + LLM**.

---

# 1. NGUYÊN TẮC THIẾT KẾ

## 1.1 Tách 2 miền dịch

Hệ thống phải tách rõ:

1. **Dịch UI E-reader**
   - Dùng **thuần QT OneMean**.
   - Không dùng LLM.
   - Không gọi provider AI.
   - Ưu tiên tốc độ, ổn định, nhất quán thuật ngữ.
   - Dùng cache vĩnh viễn theo key UI.

2. **Dịch nội dung truyện**
   - Có 2 chế độ:
     - **Thuần QT Graph**: nhanh, realtime, không tốn API.
     - **QT Graph + LLM**: QT tạo draft, LLM refine văn phong.
   - User chọn theo từng truyện/chương/toàn cục.
   - Kết quả dịch được cache tự động.
   - Không dịch lại nếu cache còn hợp lệ.
   - Chỉ đổi bản dịch khi user bấm **Dịch lại** hoặc thay đổi từ điển/graph rồi chọn cập nhật.

## 1.2 Cache là nguồn hiển thị chính

Flow đọc realtime:

```text
Text cần dịch
↓
Cache lookup
├─ hit  → trả ngay bản dịch đã lưu
└─ miss → dịch bằng mode hiện tại → lưu cache → trả kết quả
```

Không được mỗi lần mở chương lại gọi dịch lại.

## 1.3 Graph là tài sản trung tâm

Graph không chỉ là dictionary key-value. Graph chứa:

- character.
- glossary.
- terminology.
- alias.
- pronoun/xưng hô.
- cultivation rank/cảnh giới.
- place/sect/item/skill.
- style rule.
- rejected translation.
- translation memory.
- UI string memory.

User phải xem, thêm, sửa, khóa, merge, xoá mềm các mục này.

## 1.4 Realtime trước, LLM sau

Để đạt realtime:

- UI: QT OneMean local/cache-only.
- Quick translate: QT Graph local/server cache-first.
- Chapter view: prefetch + segment cache.
- LLM chạy nền, không block UI đọc.
- Khi LLM refine xong, UI có thể báo “bản dịch mượt hơn đã sẵn sàng”.

---

# 2. KIẾN TRÚC ĐÍCH

```text
                 E-reader App
                      │
        ┌─────────────┼────────────────┐
        ▼             ▼                ▼
   UI Translation  Quick Translate  Novel Reader
   QT OneMean      QT Graph         Cache-first
        │             │                │
        └──────┬──────┴────────┬───────┘
               ▼               ▼
       Local Translation Cache  Provider Settings
               │               │
               └──────┬────────┘
                      ▼
              Translation Gateway
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
      QT Graph    LLM Refiner   Graph Admin
          │           │            │
          └──────┬────┴────────────┘
                 ▼
          Translator Engine Pipeline
                 │
 Raw → QT Draft → Optional LLM → Cache → Final → Graph Feedback
```

---

# 3. DỊCH UI E-READER BẰNG QT ONEMEAN

## 3.1 Mục tiêu

Dịch toàn bộ UI, không chỉ truyện:

- `strings.xml`.
- menu XML.
- preference XML.
- dialog/toast/snackbar.
- error message.
- source debug label.
- setting title/summary.
- book source UI.
- hardcoded literal trong Kotlin.

## 3.2 Engine UI

Engine: **QT OneMean**.

Quy tắc:

- 1 source string → 1 nghĩa chuẩn theo UI glossary.
- Không dùng LLM.
- Không tự sáng tạo văn phong.
- Ưu tiên ngắn, dễ hiểu, đồng bộ.
- Preserve placeholder:
  - `%s`, `%1$s`, `%d`, `%1$d`
  - `{name}`
  - `$count`
  - XML entity: `&amp;`, `&lt;`, `\n`
  - HTML tag: `<b>`, `<br>`

## 3.3 UI cache

Key cache:

```text
ui:{resource_key}:{source_hash}:{target_lang}:{glossary_version}
```

Nếu source không đổi và glossary version không đổi → không dịch lại.

## 3.4 UI inventory

Tạo inventory:

```json
{
  "key": "book_source",
  "source": "Book Source",
  "current": "Nguồn truyện",
  "module": "app",
  "file": "app/src/main/res/values/strings.xml",
  "domain": "ui",
  "status": "locked|translated|needs_review|missing",
  "placeholders": [],
  "notes": ""
}
```

## 3.5 UI workflow

```text
Scan UI strings
↓
Build inventory
↓
QT OneMean translate missing/changed only
↓
QC placeholder/XML/CJK
↓
Generate patch
↓
User review/lock
↓
Save UI memory
```

## 3.6 UI QC bắt buộc

- Không mất placeholder.
- XML parse OK.
- Không còn CJK trong UI Vietnamese, trừ whitelist.
- Không còn English key user-facing, trừ technical whitelist.
- Không làm dài quá mức button/menu ngắn.
- Không overwrite string đã `locked`.

---

# 4. DỊCH NỘI DUNG TRUYỆN

## 4.1 Chế độ dịch

### Mode A — Thuần QT Graph

Dùng khi:

- đọc realtime.
- user muốn nhanh.
- không có mạng/API.
- test từ điển/graph.
- dịch nháp hàng loạt.

Flow:

```text
Raw text
↓
Normalize + segment
↓
Cache lookup
↓ miss
Graph lookup: character/glossary/TM/pronoun/style
↓
QT Graph render
↓
Save cache
↓
Return realtime
```

### Mode B — QT Graph + LLM

Dùng khi:

- xuất bản dịch final.
- user muốn văn phong mượt.
- dịch batch.
- chương quan trọng.

Flow:

```text
Raw text
↓
QT Graph draft
↓
Context Pack
↓
LLM refine
↓
QC
↓
Save refined cache + TM + graph feedback
↓
Return final
```

## 4.2 Cache nội dung

Cache theo cấp:

1. **segment cache**: câu/đoạn nhỏ.
2. **paragraph cache**: đoạn hiển thị.
3. **chapter cache**: toàn chương.
4. **final cache**: output đã QC.

Cache key:

```text
content:{book_id}:{chapter_id}:{segment_hash}:{mode}:{graph_version}:{provider_id}:{prompt_version}
```

Mode QT-only không phụ thuộc `provider_id/prompt_version`.

## 4.3 Quy tắc không tự đổi bản dịch

Nếu cache hit:

- hiển thị cache.
- không gọi dịch lại.
- không tự update vì provider/graph đổi.

Chỉ dịch lại khi:

- user bấm **Dịch lại đoạn**.
- user bấm **Dịch lại chương**.
- user chọn **Áp dụng thay đổi graph cho chương này**.
- user xoá cache.
- source raw đổi hash.

## 4.4 Re-translate options

UI cần các lựa chọn:

- Dịch lại đoạn này.
- Dịch lại chương này.
- Dịch lại từ chương hiện tại trở đi.
- Dịch lại toàn bộ truyện.
- Dịch lại chỉ bằng QT Graph.
- Dịch lại QT Graph + LLM.
- Giữ bản cũ nhưng cập nhật dictionary.
- So sánh bản cũ/mới.

---

# 5. QT GRAPH MODEL

## 5.1 Node types

- `character`: nhân vật.
- `alias`: bí danh/tên khác.
- `glossary`: thuật ngữ chung.
- `term`: token/từ/cụm.
- `place`: địa danh.
- `sect`: tông môn/tổ chức.
- `item`: vật phẩm/pháp bảo.
- `skill`: công pháp/kỹ năng.
- `rank`: cảnh giới/cấp bậc.
- `pronoun`: xưng hô.
- `style`: quy tắc văn phong.
- `ui_string`: chuỗi UI.
- `tm_segment`: translation memory.
- `rejected`: bản dịch bị loại.

## 5.2 Edge types

- `translates_to`.
- `alias_of`.
- `same_as`.
- `belongs_to_book`.
- `belongs_to_genre`.
- `appears_in_chapter`.
- `relationship_to`.
- `preferred_in_context`.
- `rejected_in_context`.
- `uses_pronoun`.
- `ui_context`.

## 5.3 Versioning

Mỗi thay đổi graph tăng version:

- `global_graph_version`.
- `book_graph_version`.
- `ui_glossary_version`.

Cache vẫn giữ version cũ. User chọn mới update.

---

# 6. TRÌNH QUẢN LÝ GRAPH CHO USER

## 6.1 Màn hình cần có trong E-reader

### Graph Dictionary

Chức năng:

- xem danh sách term.
- tìm kiếm raw/translated.
- thêm term.
- sửa bản dịch.
- khóa term.
- đánh dấu sai.
- merge duplicate.
- import/export.

Fields:

- raw.
- translated.
- type.
- confidence.
- source.
- domain.
- book scope.
- locked.
- notes.

### Character Manager

Chức năng:

- xem nhân vật.
- alias.
- giới tính nếu biết.
- vai trò.
- xưng hô.
- quan hệ.
- bản dịch tên.
- khóa tên.

Fields:

- raw_name.
- vi_name.
- aliases.
- gender.
- role.
- first_seen_chapter.
- last_seen_chapter.
- pronoun_rule.
- locked.

### Glossary Manager

Chức năng:

- thuật ngữ tiên hiệp/huyền huyễn/game/system.
- cảnh giới.
- vật phẩm.
- kỹ năng.
- địa danh.
- tổ chức.

### Translation Memory Viewer

Chức năng:

- xem raw → translated.
- filter theo truyện/chương/mode/provider.
- chỉnh sửa bản dịch.
- lock memory.
- xoá cache sai.

### Cache Manager

Chức năng:

- xem cache theo truyện/chương.
- xoá cache đoạn/chương/truyện.
- pin bản dịch.
- chọn bản dịch cũ/mới.



## 6.3 Bổ sung/sửa từ điển trực tiếp bằng long click và bôi đen cụm từ

Mục tiêu: khi đang đọc truyện, user có thể chọn ngay một cụm từ trong nội dung để thêm/sửa dictionary graph mà không phải rời màn đọc.

### 6.3.1 Entry points trong Reader

1. **Long click trên một từ/cụm từ**
   - App tự chọn token gần vị trí nhấn.
   - Hiện menu nhanh:
     - Thêm vào từ điển.
     - Sửa bản dịch cụm này.
     - Đặt là nhân vật.
     - Đặt là thuật ngữ/glossary.
     - Đặt là địa danh/tông môn/vật phẩm/kỹ năng.
     - Xem trace dịch.
     - Dịch lại đoạn này.

2. **Bôi đen cụm từ thủ công**
   - User kéo chọn cụm raw hoặc cụm bản dịch.
   - Hiện action bar:
     - Thêm/Sửa Graph.
     - Khóa bản dịch.
     - Thêm alias.
     - Gộp với mục có sẵn.
     - Đánh dấu bản dịch sai.
     - Dịch lại đoạn/chương với thay đổi mới.

3. **Long click trên bản dịch đã hiển thị**
   - Cho sửa target Vietnamese.
   - Có tùy chọn áp dụng cho:
     - chỉ segment hiện tại.
     - toàn chương.
     - toàn truyện.
     - global graph.

### 6.3.2 Dialog thêm/sửa nhanh

Dialog cần các field:

- `Raw phrase`: cụm gốc được chọn.
- `Vietnamese translation`: bản dịch mong muốn.
- `Type`:
  - character.
  - glossary.
  - term.
  - place.
  - sect.
  - item.
  - skill.
  - rank.
  - pronoun.
- `Scope`:
  - current segment.
  - current chapter.
  - current book.
  - global.
  - UI only.
- `Locked`: khóa, không cho LLM/QT đổi.
- `Alias of`: chọn mục graph có sẵn nếu đây là bí danh.
- `Note`: ghi chú ngữ cảnh.
- `Apply now`:
  - không áp dụng cache cũ.
  - dịch lại đoạn hiện tại.
  - dịch lại chương hiện tại.

### 6.3.3 Luồng xử lý

```text
User long click / bôi đen
↓
Reader lấy raw selection + translated selection + book/chapter/segment context
↓
Mở Quick Graph Edit dialog
↓
User nhập bản dịch + type + scope
↓
POST /api/v1/graph/quick-edit
↓
Graph tăng version theo scope
↓
Cache cũ giữ nguyên
↓
Nếu user chọn Apply now → force retranslate selected segment/chapter
```

### 6.3.4 API quick edit

`POST /api/v1/graph/quick-edit`

Request:

```json
{
  "raw": "原文短语",
  "translated": "bản dịch mong muốn",
  "type": "character|glossary|term|place|sect|item|skill|rank|pronoun",
  "scope": "segment|chapter|book|global|ui",
  "locked": true,
  "alias_of": null,
  "context": {
    "book_id": "book-1",
    "chapter_id": "ch-1",
    "segment_id": "p12",
    "raw_sentence": "...",
    "current_translation": "..."
  },
  "apply": {
    "mode": "none|segment|chapter",
    "translation_mode": "qt_graph|qt_llm"
  }
}
```

Response:

```json
{
  "ok": true,
  "term_id": "term-123",
  "graph_version": 18,
  "cache_changed": false,
  "retranslated": {
    "segment_id": "p12",
    "translated": "bản dịch mới"
  }
}
```

### 6.3.5 Quy tắc cache khi sửa bằng long click

- Thêm/sửa graph **không tự sửa cache cũ**.
- Nếu `Apply now = none`: chỉ lưu graph, bản đang đọc giữ nguyên.
- Nếu `Apply now = segment`: chỉ xóa/dịch lại cache segment đang chọn.
- Nếu `Apply now = chapter`: xóa/dịch lại cache chương hiện tại.
- Nếu term `locked=true`: lần dịch lại sau bắt buộc dùng bản dịch mới.

### 6.3.6 Trace và gợi ý tự động

Khi user chọn cụm từ:

- App gọi `GET /api/v1/graph/suggest?raw=...&book_id=...`.
- Hiển thị mục gần giống:
  - exact match.
  - alias candidate.
  - fuzzy raw.
  - cùng bản dịch Vietnamese.
- Nếu cụm đã có trong graph:
  - mở chế độ sửa thay vì thêm mới.
- Nếu cụm xuất hiện nhiều lần trong chương:
  - hỏi user có áp dụng cho tất cả occurrence không.

### 6.3.7 UX yêu cầu

- Menu long-click phải nhanh, không chờ LLM.
- Dialog có autocomplete từ graph hiện có.
- Có nút “Hoàn tác thay đổi gần nhất”.
- Có lịch sử sửa graph theo user/time.
- Có cảnh báo khi sửa global scope vì ảnh hưởng nhiều truyện.
- Có preview trước/sau khi dịch lại segment.

## 6.2 Dashboard bên Translator Engine

Nếu quản lý trong dashboard dễ hơn, tạo các page:

- `/graph/terms`
- `/graph/characters`
- `/graph/glossary`
- `/graph/tm`
- `/graph/cache`
- `/providers`
- `/jobs`
- `/ui-strings`

E-reader có thể mở WebView dashboard hoặc gọi API native.

---

# 7. PROVIDER SETTINGS

## 7.1 Provider dùng cho nội dung, không dùng cho UI QT OneMean

UI translation không gọi LLM provider.

Provider settings dùng cho:

- QT Graph server endpoint.
- LLM refiner.
- embedding optional.
- fallback provider.

## 7.2 Setting cần thêm trong E-reader

### Gateway

- bật/tắt Translation Gateway.
- Gateway URL.
- test kết nối.
- timeout.
- cache enabled.
- debug trace enabled.

### Dịch UI

- UI engine: cố định `QT OneMean`.
- UI glossary version.
- scan UI strings.
- dịch UI missing only.
- QC UI.
- import translated resources.

### Dịch nội dung

- default mode:
  - QT Graph.
  - QT Graph + LLM.
- default QT provider.
- default LLM provider.
- allow remote LLM for book content.
- auto prefetch translate next chapter.
- realtime segment size.
- cache policy.
- retranslate policy.

### Graph

- mở Dictionary Manager.
- mở Character Manager.
- mở Glossary Manager.
- mở TM/Cache Manager.
- sync graph.
- export/import graph.

## 7.3 Provider schema

```json
{
  "id": "llm-main",
  "name": "LLM Main",
  "type": "llm_refiner",
  "enabled": true,
  "base_url": "https://api.example.com/v1",
  "api_key_ref": "LLM_MAIN_API_KEY",
  "model": "model-name",
  "timeout_sec": 90,
  "max_retries": 2,
  "capabilities": ["novel_refine", "entity_extract"],
  "privacy": {
    "allow_send_book_content": true,
    "allow_send_ui_strings": false
  }
}
```

---

# 8. REALTIME PERFORMANCE PLAN

## 8.1 Latency targets

- UI string lookup: `< 5ms` per string after cache.
- Quick translate selected sentence: `< 100ms` QT Graph cache hit.
- Quick translate paragraph QT miss: `< 500ms`.
- Chapter open with existing cache: instant/readable `< 300ms` first screen.
- Background full chapter QT: acceptable vài giây tùy độ dài.
- LLM refine: async, không block reader.

## 8.2 Optimization tasks

### Cache-first

- in-memory LRU cache for current book/chapter.
- disk SQLite cache for persistent results.
- preload next/previous chapter cache.
- cache by segment hash.

### Segmentation

- split theo paragraph trước.
- split long paragraph thành sentence.
- preserve punctuation and quote marks.
- avoid resegment if chapter hash unchanged.

### Graph lookup

- normalized trie/Aho-Corasick for term matching.
- longest-match wins.
- locked terms override all.
- book graph overrides global graph.
- UI glossary separate from novel graph.

### Batch calls

- E-reader sends batch segments.
- Translator Engine returns streaming or chunked result.
- UI renders progressively.

### Background workers

- reading screen only requests visible paragraphs first.
- next N paragraphs translate in background.
- next chapter prefetch when idle.
- LLM refine queue low priority.

### Indexing

- index raw_hash.
- index book_id/chapter_id.
- index node normalized text.
- index alias/translation.

---

# 9. API CONTRACT

## 9.1 QT realtime translate

`POST /api/v1/qt/translate`

Request:

```json
{
  "domain": "ui|quick|novel",
  "mode": "qt_graph",
  "source_lang": "zh",
  "target_lang": "vi",
  "items": [
    {
      "id": "p1",
      "text": "原文",
      "context": {
        "book_id": "book-1",
        "chapter_id": "ch-1",
        "ui_key": null
      }
    }
  ],
  "cache": {
    "read": true,
    "write": true,
    "force_retranslate": false
  },
  "options": {
    "return_trace": false,
    "visible_first": true
  }
}
```

Response:

```json
{
  "items": [
    {
      "id": "p1",
      "translated": "Bản dịch",
      "cache_status": "hit|miss|refreshed",
      "graph_version": 12,
      "confidence": 0.88,
      "trace": []
    }
  ]
}
```

## 9.2 LLM refine

`POST /api/v1/llm/refine`

Request:

```json
{
  "book_id": "book-1",
  "chapter_id": "ch-1",
  "provider_id": "llm-main",
  "items": [
    {
      "id": "p1",
      "raw": "原文",
      "qt": "QT draft"
    }
  ],
  "cache": {
    "read": true,
    "write": true,
    "force_retranslate": false
  }
}
```

## 9.3 Cache operations

- `GET /api/v1/cache/book/{book_id}`
- `DELETE /api/v1/cache/book/{book_id}`
- `DELETE /api/v1/cache/book/{book_id}/chapter/{chapter_id}`
- `POST /api/v1/cache/retranslate`

## 9.4 Graph operations

- `GET /api/v1/graph/terms`
- `POST /api/v1/graph/terms`
- `PATCH /api/v1/graph/terms/{id}`
- `POST /api/v1/graph/terms/{id}/lock`
- `POST /api/v1/graph/terms/merge`
- `GET /api/v1/graph/characters`
- `POST /api/v1/graph/characters`
- `PATCH /api/v1/graph/characters/{id}`
- `GET /api/v1/graph/glossary`
- `GET /api/v1/graph/tm`

---

# 10. PHASE TRIỂN KHAI CHI TIẾT

## Phase 1 — Chuẩn hóa schema + inventory

Mục tiêu: biết chính xác cần dịch gì, lưu gì, gọi API gì.

### Task 1.1 — E-reader UI inventory

- Quét `app/src/main/res/values*/strings.xml`.
- Quét `menu/*.xml`.
- Quét `xml/*preference*.xml` nếu có.
- Quét Kotlin hardcoded strings.
- Xuất `Temp/ui_string_inventory.json`.
- Đánh dấu:
  - static resource.
  - runtime string.
  - setting string.
  - source/debug string.

### Task 1.2 — Translator Engine schema

Tạo:

- `Plan/provider_schema.json`.
- `Plan/qt_graph_api_contract.md`.
- `Plan/qt_graph_db_schema.md`.

### Task 1.3 — Cache policy document

Tạo:

- `Plan/cache_policy.md`.

Nội dung:

- cache key.
- khi nào hit/miss.
- khi nào dịch lại.
- xóa cache thế nào.
- graph version ảnh hưởng ra sao.

### Task 1.4 — UI QT OneMean glossary seed

Tạo:

- `Config/ui_onemean_glossary.json`.

Seed thuật ngữ:

- Book Source → Nguồn truyện.
- Bookshelf → Tủ sách.
- Replace Rule → Quy tắc thay thế.
- Web Service → Máy chủ Web.
- Chapter → Chương.
- Search → Tìm kiếm.

Exit criteria:

- Có inventory UI.
- Có schema provider/API/cache.
- Có glossary seed.

---

## Phase 2 — Provider Settings + Gateway Client

Mục tiêu: E-reader cấu hình được gateway/provider; chưa cần LLM cho UI.

### E-reader tasks

1. Thêm model `TranslationProvider`.
2. Thêm model `TranslationGatewayConfig`.
3. Thêm setting screen:
   - Gateway URL.
   - Test Gateway.
   - Default content mode.
   - Default LLM provider.
   - Cache enabled.
   - Privacy toggles.
4. Thêm Provider Manager:
   - list/add/edit/delete/test.
   - mask API key.
   - import/export provider without secrets.
5. Thêm `TranslationGatewayClient`:
   - `testGateway()`.
   - `qtTranslateBatch()`.
   - `llmRefineBatch()`.
   - `getGraphTerms()`.
   - `saveGraphTerm()`.

### Translator Engine tasks

1. Thêm provider registry:
   - load JSON.
   - resolve env var.
   - validate capabilities.
2. Thêm endpoint gateway health:
   - `/api/v1/health`.
3. Thêm endpoint provider test:
   - `/api/v1/providers/{id}/test`.
4. Không dùng provider cho UI OneMean.

Exit criteria:

- E-reader test được gateway.
- Provider LLM test được.
- Setting lưu được mode mặc định.

---

## Phase 3 — QT Graph Core + Cache

Mục tiêu: dịch realtime bằng QT Graph và cache tự động.

### Translator Engine tasks

1. Tạo module:
   - `Script/qt_graph/store.py`.
   - `Script/qt_graph/cache.py`.
   - `Script/qt_graph/onemean.py`.
   - `Script/qt_graph/translator.py`.
   - `Script/qt_graph/segmenter.py`.
2. Tạo DB tables:
   - graph nodes.
   - graph edges.
   - translation cache.
   - translation memory.
   - UI memory.
3. Implement cache:
   - get/set by hash.
   - force retranslate.
   - invalidate by book/chapter/domain.
4. Implement QT OneMean:
   - exact glossary hit.
   - longest term match.
   - placeholder protect.
   - UI domain only.
5. Implement QT Graph content translator:
   - segment.
   - TM exact hit.
   - dictionary graph hit.
   - character/glossary/pronoun replacement.
   - confidence scoring.
6. Add tests:
   - placeholder safe.
   - cache hit skip translate.
   - force retranslate changes result.
   - graph locked term wins.

### E-reader tasks

1. Call `qtTranslateBatch` for selected text.
2. Cache local visible paragraph results.
3. Render cached translation first.
4. Add “Dịch lại” action.

Exit criteria:

- Quick Translate realtime với cache.
- Không dịch lại khi cache hit.
- Force retranslate hoạt động.

---

## Phase 4 — UI Translation bằng QT OneMean

Mục tiêu: dịch UI toàn app bằng QT OneMean, QC an toàn.

### Translator Engine tasks

1. Tạo script `Script/ui_string_inventory.py`.
2. Tạo script `Script/ui_onemean_translate.py`.
3. Tạo script `Script/ui_qc.py`.
4. Output:
   - `Temp/ui_string_inventory.json`.
   - `Temp/ui_translation_suggestions.json`.
   - `Temp/ui_qc_report.md`.
   - patch XML nếu được duyệt.
5. Không gọi LLM.
6. Lưu approved UI string vào `ui_string_memory`.

### E-reader tasks

1. Thêm screen “Dịch UI”.
2. Buttons:
   - Scan UI.
   - Dịch missing only.
   - Xem QC report.
   - Apply patch.
   - Lock selected string.
3. Có danh sách string để sửa thủ công.
4. Có filter:
   - missing.
   - changed.
   - needs review.
   - locked.

Exit criteria:

- UI có thể dịch lại lặp lại an toàn.
- Placeholder không vỡ.
- Không gọi LLM cho UI.

---

## Phase 5 — Graph Editor

Mục tiêu: user xem/sửa/bổ sung dictionary graph/character/glossary.

### Translator Engine tasks

1. API CRUD terms.
2. API CRUD characters.
3. API CRUD glossary.
4. API TM/cache viewer.
5. API lock/unlock.
6. API merge alias/duplicate.
7. API import/export graph JSON.
8. Audit log:
   - ai/user/system.
   - old value/new value.
   - timestamp.

### E-reader tasks

1. Dictionary screen.
2. Character screen.
3. Glossary screen.
4. TM/cache screen.
5. Inline action from reader:
   - long press term → “Thêm vào từ điển”.
   - selected name → “Đặt là nhân vật”.
   - selected phrase → “Khóa bản dịch”.
6. Show graph trace for translated segment:
   - term nào được dùng.
   - cache hit/miss.
   - confidence.

Exit criteria:

- User thêm/sửa character/glossary từ app.
- Dịch kế tiếp dùng rule mới.
- Bản cũ không đổi trừ khi user dịch lại.

---

## Phase 6 — Novel Pipeline 2 Mode

Mục tiêu: pipeline truyện có 2 mode: QT Graph-only và QT Graph + LLM.

### Translator Engine tasks

1. Stage 1:
   - extract entity.
   - write candidates vào graph với status `suggested`.
2. Stage 2:
   - `raw_segments[].qt` lấy từ QT Graph translator.
   - attach `graph_hits`.
   - attach `cache_status`.
3. Stage 3:
   - nếu mode `qt_graph`: bỏ qua LLM, dùng QT draft.
   - nếu mode `qt_llm`: gọi LLM refine.
4. Stage 4:
   - QC final.
   - save final cache.
   - update TM.
   - suggested graph feedback.
5. Add mode config:
   - per project.
   - per chapter override.
   - per run CLI.

### E-reader tasks

1. Book setting:
   - translation mode.
   - provider.
   - cache policy.
2. Chapter action:
   - dịch chương bằng QT.
   - dịch chương bằng QT+LLM.
   - dịch lại chương.
   - xem bản cached.
3. Reader overlay:
   - raw.
   - QT.
   - LLM final nếu có.

Exit criteria:

- Một chương chạy được 2 mode.
- Cache không đổi nếu không force.
- LLM refine chạy async.

---

## Phase 7 — Realtime Reader Optimization

Mục tiêu: đọc mượt, dịch gần realtime.

### E-reader tasks

1. Visible-first rendering:
   - dịch các paragraph đang hiển thị trước.
2. Prefetch:
   - next 5 paragraphs.
   - next chapter khi gần cuối.
3. Local LRU cache:
   - current chapter.
   - previous/next chapter.
4. Background queue:
   - low priority LLM.
   - high priority visible QT.
5. Cancel stale requests:
   - user chuyển chương thì cancel pending non-visible.
6. Offline behavior:
   - cache-only mode.
   - local QT if available.

### Translator Engine tasks

1. Batch endpoint optimized.
2. Streaming/chunk response optional.
3. Trie term matcher.
4. Warmup graph indexes.
5. Worker pool:
   - QT workers.
   - LLM workers.
   - graph write worker.
6. Metrics:
   - cache hit rate.
   - avg latency.
   - graph hit rate.
   - LLM queue time.

Exit criteria:

- Opening cached chapter feels instant.
- QT visible paragraph returns fast.
- LLM never blocks reading.

---

## Phase 8 — Dashboard/Review

Mục tiêu: kiểm soát chất lượng và dữ liệu graph.

### Dashboard pages

1. Providers.
2. Jobs.
3. Cache.
4. Terms.
5. Characters.
6. Glossary.
7. UI strings.
8. QC reports.
9. Low-confidence suggestions.
10. Rejected translations.

### Review flows

- approve suggested character.
- reject bad translation.
- lock glossary term.
- merge aliases.
- rerun selected chapter after graph edit.
- export/import graph.

Exit criteria:

- Có review loop hoàn chỉnh.
- Graph không bị ô nhiễm bởi output xấu chưa duyệt.

---

## Phase 9 — Test Matrix

### UI tests

- placeholder unchanged.
- XML valid.
- UI QT OneMean no LLM call.
- locked UI string not overwritten.
- missing UI detected.

### Cache tests

- cache hit returns old translation.
- graph edit does not auto change old cache.
- force retranslate updates cache.
- delete chapter cache works.

### Graph tests

- locked character name wins.
- book graph overrides global graph.
- rejected translation not reused.
- alias merge works.

### Pipeline tests

- QT-only chapter.
- QT+LLM chapter.
- LLM provider fail → QT fallback.
- Stage 4 TM update.
- CJK QC final.

### Realtime tests

- visible paragraph priority.
- cancel stale request.
- next chapter prefetch.
- cold cache vs warm cache latency.

---

# 11. THỨ TỰ TRIỂN KHAI KHUYẾN NGHỊ

1. Viết schema/cache/API contract.
2. Làm Provider Settings + Gateway health.
3. Làm QT Graph cache-first core.
4. Làm Quick Translate realtime.
5. Làm UI inventory + QT OneMean translate + QC.
6. Làm Graph Editor cơ bản: term/character/glossary.
7. Gắn QT Graph vào Stage 2 pipeline.
8. Thêm mode QT-only/QT+LLM cho chapter.
9. Thêm reader prefetch/realtime optimization.
10. Thêm dashboard review.

---

# 12. TASK NGAY SAU PLAN

## Task A — tạo schema files

- `/sdcard/My Agent/Translator Engine/Plan/provider_schema.json`
- `/sdcard/My Agent/Translator Engine/Plan/qt_graph_api_contract.md`
- `/sdcard/My Agent/Translator Engine/Plan/cache_policy.md`

## Task B — tạo UI inventory tool

- `Script/ui_string_inventory.py`
- input: path e-reader.
- output: `Temp/ui_string_inventory.json`.

## Task C — tạo QT Graph skeleton

- `Script/qt_graph/__init__.py`
- `Script/qt_graph/cache.py`
- `Script/qt_graph/store.py`
- `Script/qt_graph/onemean.py`
- `Script/qt_graph/translator.py`

## Task D — tạo graph editor API skeleton

- terms CRUD.
- characters CRUD.
- glossary CRUD.
- cache read/delete.

## Task F — Reader long-click graph edit spec

- xác định reader text selection API hiện tại.
- thêm menu long-click/bôi đen cụm từ.
- thiết kế Quick Graph Edit dialog.
- thêm API `/api/v1/graph/quick-edit`.
- thêm force retranslate selected segment/chapter.

## Task E — E-reader settings spec

- xác định file settings hiện tại.
- thêm màn provider/gateway/translation/cache/graph.

---

# 13. DEFINITION OF DONE

Hoàn thành khi:

1. UI E-reader dịch bằng QT OneMean, không LLM.
2. UI resource có inventory, cache, QC, lock.
3. Nội dung truyện có 2 mode: QT Graph và QT Graph + LLM.
4. Cache tự động lưu bản dịch.
5. Cache không tự đổi nếu user không bấm dịch lại.
6. User xem/sửa/bổ sung dictionary graph.
7. User quản lý character/glossary/pronoun/TM/cache.
8. Reader dịch realtime theo visible-first + prefetch.
9. Provider settings hoạt động.
10. Pipeline Stage 2 dùng QT Graph.
11. Stage 4 cập nhật TM/graph có kiểm soát.
12. Demo thành công:
    - dịch UI missing-only bằng QT OneMean.
    - quick translate đoạn đang đọc realtime.
    - dịch chương bằng QT-only.
    - dịch chương bằng QT+LLM.
    - sửa character trong graph rồi dịch lại chương để thấy thay đổi.
