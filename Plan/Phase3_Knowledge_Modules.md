# KẾ HOẠCH PHASE 3: NÂNG CAO — Module Tri Thức (1-2 tuần)

**Mục tiêu:** Kích hoạt toàn bộ tiềm năng của Kiến trúc Đồ thị Tri thức (Knowledge Base). Khai thác cơ sở dữ liệu đồ sộ đã có sẵn để tối ưu hóa khả năng dịch tự động và tiết kiệm tài nguyên AI.
**Thời gian ước tính:** 1-2 tuần

---

## Task 3.1: Translation Memory Lookup (Tái sử dụng kết quả dịch)

**Mô tả vấn đề:**
- Bảng `kb_translation_memory` đã tồn tại trong database mới nhưng hệ thống dịch thuật lại hoàn toàn chưa tận dụng nó.
- Nếu một đoạn văn/câu đã từng được dịch và tối ưu, hệ thống đang phải yêu cầu AI làm lại từ đầu.

**Giải pháp:**
- Phát triển module `tm_lookup.py` để tìm kiếm các bản dịch mẫu dựa trên mã hash hoặc tìm kiếm Fuzzy.
- Tích hợp kết quả tìm được vào Context Pack. Báo cho AI biết đây là cách dịch mà hệ thống ưu tiên.

**Code Skeleton/Pseudocode:**
```python
class TMEngine:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path)
    
    def lookup(self, text, project_scope=None):
        raw_hash = generate_md5(text)
        # Truy vấn Exact Match
        cursor = self.db.execute("SELECT translated_text FROM kb_translation_memory WHERE raw_hash = ?", (raw_hash,))
        res = cursor.fetchone()
        if res:
            return res[0]
        # Nếu cần, phát triển Fuzzy match sau
        return None

    def save(self, raw_text, translated_text, project_scope=None):
        # Update hoặc Insert vào DB
        pass
```

**Các bước thực hiện:**
1. Tạo class `TMEngine` trong `Script/tm_lookup.py`.
2. Trong file `stage2_context_pack.py`, thêm thông tin mảng `similar_translations` vào object Context.
3. Trong `qt_engine.py`, thêm fallback: nếu đoạn dịch tồn tại trong TM thì lấy trực tiếp không cần tính toán bằng đồ thị từ điển.

**Checklist hoàn thành:**
- [ ] Module `TMEngine` hoạt động tốt với CSDL `kb_translation_memory`.
- [ ] AI có nhận được dữ liệu `similar_translations`.
- [ ] `QTEngine` tiết kiệm được bước dịch nếu dính Exact Match.

---

## Task 3.2: Grammar Rules từ DB

**Mô tả vấn đề:**
- File `Script/grammar.py` hiện tại đang hardcode toàn bộ bộ quy tắc ngữ pháp.
- Đường dẫn lưu log của Grammar lại trỏ về một source cũ đã không còn tồn tại (`/sdcard/My Agent/Transbot`).

**Giải pháp:**
- Chuyển việc tải ngữ pháp sang đọc từ bảng `kb_grammar_rule`.
- Sử dụng fallback xuống rules tĩnh trong trường hợp DB trống.

**Các bước thực hiện:**
1. Refactor file `grammar.py` chuyển thành class `GrammarEngine`.
2. Tạo hàm `load_rules_from_db()`.
3. Sửa lại tham số và thư mục lưu trữ Log thành cấu trúc hiện tại (`/sdcard/my agent/Translator Engine/logs/`).
4. (Optional) Tạo thêm Bot Command cho Admin để thêm Rule trực tiếp thông qua Telegram.

**Checklist hoàn thành:**
- [ ] Xóa bỏ phụ thuộc đường dẫn Transbot.
- [ ] Có thể thay đổi ngữ pháp mà không cần can thiệp trực tiếp mã nguồn.

---

## Task 3.3: Knowledge Extractor (Tự động Trích xuất Tri thức)

**Mô tả vấn đề:**
- Mới chỉ lấy kết quả bản dịch của AI (Stage 3), chưa có module trích xuất tự động các thuật ngữ, nhân vật mới từ bản dịch để hệ thống tự học.

**Giải pháp:**
- Phát triển module sau Stage 3 để đối chiếu `new_entities` do AI đề xuất với Knowledge Base hiện có.
- Nếu thực sự mới, đẩy sang dạng Candidate để chuẩn bị phê duyệt.

**Các bước thực hiện:**
1. Xây dựng file `Script/knowledge_extractor.py`.
2. So khớp AI Output với `kb_node` hiện có.
3. Nếu không tìm thấy, lưu xuống bảng tạm (hoặc dùng cờ `status='candidate'`).
4. Gắn hàm này chạy sau Stage 3 và trước Stage 4.

**Checklist hoàn thành:**
- [ ] Tự động nhận dạng thuật ngữ/nhân vật mới sau dịch.

---

## Task 3.4: Knowledge Validator

**Mô tả vấn đề:**
- Các candidate sinh ra từ AI cần một quy trình xét duyệt để đảm bảo chất lượng tri thức không bị vấy bẩn.

**Giải pháp:**
- Tính toán điểm (Scoring): Tần suất lặp lại (Frequency) x Mức độ phù hợp ngữ cảnh (Context relevance).
- Dưới mức cho phép -> Admin (qua Telegram) bấm nút Approve/Reject.
- Trên mức cao -> Auto-approve thẳng vào `kb_node`.

**Các bước thực hiện:**
1. Thêm `Script/knowledge_validator.py`.
2. Tích hợp tính năng Admin Notification trong Bot để gửi Telegram (tạo inline button Approve/Reject).
3. Hàm update lại status của node khi có tương tác.

**Checklist hoàn thành:**
- [ ] Có UI Telegram để Admin xem duyệt thuật ngữ mới.

---

## Task 3.5: Quality Control (QC) Module

**Mô tả vấn đề:**
- Bản dịch Final đôi lúc có thể bị sai tên nhân vật, sai số liệu so với bản Raw, hoặc format đoạn thụt lề sai do AI "ảo giác".

**Giải pháp:**
- Viết `Script/qc_checker.py` chạy trước Stage 4.
- Đối chiếu số lượng đoạn (Paragraph count), phát hiện mất thông tin (số, dấu ngoặc).
- Đảm bảo tên các Character có trong `kb_node` không bị biến dạng.

**Các bước thực hiện:**
1. Viết bộ regex để check các con số trong Raw và Final.
2. Nếu lỗi nghiêm trọng, bắn cảnh báo Telegram.

**Checklist hoàn thành:**
- [ ] Chặn được bản dịch mất chữ/số.

---

## Task 3.6: Relationship Graph

**Mô tả vấn đề:**
- Các bảng `kb_edge` và `kb_edge_history` đã được tạo nhưng chưa có mã nguồn tác động lên.

**Giải pháp:**
- Xây dựng `Script/relationship_manager.py`.
- Tự động detect quan hệ (ví dụ AI phân loại: master_of, enemy_of, spouse_of).
- Track lại sự thay đổi mối quan hệ dựa vào tiến độ chương.

**Checklist hoàn thành:**
- [ ] Bảng `kb_edge` bắt đầu có dữ liệu.

---
**TỔNG KẾT PHASE 3:** Hoàn thành giai đoạn này, TKP sẽ thực sự trở thành hệ thống "học tri thức", tăng độ thông minh theo thời gian.
