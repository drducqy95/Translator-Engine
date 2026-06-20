# KẾ HOẠCH PHASE 4: HOÀN THIỆN — Tính năng nâng cao (2-4 tuần)

**Mục tiêu:** Nâng tầm hệ thống thành một nền tảng vận hành liên tục, chuyên nghiệp với đầy đủ tự động hóa: tự phân tích, tự xuất báo cáo và giao diện Dashboard đồ họa đẹp mắt.
**Thời gian ước tính:** 2-4 tuần

---

## Task 4.1: Evolution Engine (Cơ chế tự tiến hóa)

**Mô tả vấn đề:**
- Hệ thống cần tự động sinh ra rule ngữ pháp, rule biên tập từ điển mới dựa trên tần suất chỉnh sửa lặp lại của AI so với bản Draft của QTEngine.

**Giải pháp:**
- Chạy batch script: Cứ mỗi 50 chương được xử lý xong, sẽ tiến hành phân tích mã Diff.
- Trích xuất ra các pattern thay thế cố định.

**Code Skeleton/Pseudocode:**
```python
class EvolutionEngine:
    def compare_and_extract(self, novel_id, recent_n_chapters=50):
        # Đọc 50 bản draft.md và final.md
        # Tạo hàm diff mức từ vựng
        # Thống kê tần suất: VD "Linh thạch" -> "Linh Thạch" (count = 120 lần)
        # Nếu count > Threshold, tạo proposal update Style Graph
        pass
```

**Các bước thực hiện:**
1. Code `Script/evolution_engine.py` ứng dụng thuật toán Sequence Matcher.
2. Tạo job định kỳ để gọi Evolution Engine theo số lượng chương đã publish.

**Checklist hoàn thành:**
- [ ] Tự đề xuất các quy tắc dịch mới được AI dùng nhiều lần.

---

## Task 4.2: Tích hợp đầy đủ Stage 5 Git Push

**Mô tả vấn đề:**
- `stage5_git_push.py` hiện tại mới chỉ là đoạn code placeholder, comment lệnh git.

**Giải pháp:**
- Mở command git và xử lý Exception nếu kết nối Git lỗi để tránh việc pipeline bị khựng lại.

**Các bước thực hiện:**
1. Cấu hình git remote.
2. Thêm logic: `git add .`, `git commit -m "[Auto] Translated {novel}: Chapter {X}-{Y}"`, `git push`.
3. Có Timeout / Retries cho network.

**Checklist hoàn thành:**
- [ ] Code được tự động backup lên repo đám mây.

---

## Task 4.3: Dashboard Nâng Cao

**Mô tả vấn đề:**
- Thư mục Dashboard/ hiện tại chỉ mới dựng bộ khung ban đầu hiển thị thông tin Crawl sơ khai bằng Flask. Chưa tương tác sâu với Knowledge Base.

**Giải pháp:**
- Tích hợp CRUD API và Views cho các trang: Characters, Glossary, Relationships, Translation Memory.
- Bổ sung màn hình Pipeline Monitor giám sát real-time các daemon của Bot Telegram.
- Vẽ biểu đồ thống kê KPI (Tốc độ dịch chương/ngày, AI Token Cost).

**Các bước thực hiện:**
1. Dùng Flask-Restful sinh các endpoint.
2. Cập nhật frontend `index.html` dùng Chart.js hoặc thư viện UI Framework như Tailwind/Vue.js.
3. Vẽ đồ thị tiến độ xử lý của Worker.

**Checklist hoàn thành:**
- [ ] Có giao diện web trực quan để quản lý kho tri thức của các dự án truyện.

---

## Task 4.4: Scheduler Linh Hoạt (Branch Scheduler)

**Mô tả vấn đề:**
- Bot V2 đang chạy vòng lặp daemon vĩnh viễn quét các truyện. Thiết kế này cào liên tục, không thể giãn cách tiến độ ưu tiên theo dự án (như ưu tiên dịch truyện A, mỗi ngày 2 chương truyện B).

**Giải pháp:**
- Tách luồng điều phối thành Job Queue với `scheduler.py` chuyên biệt.
- Hỗ trợ cron ảo: Truyện A 5 phút dịch 1 chương, Truyện B 30 phút dịch 1 chương.

**Các bước thực hiện:**
1. Sử dụng thư viện `APScheduler` hoặc tự dựng Priority Queue bằng Threading.
2. Update lệnh điều khiển Telegram cho phép thiết lập độ ưu tiên.

**Checklist hoàn thành:**
- [ ] Job queue linh hoạt hoạt động.

---

## Task 4.5: Mở rộng khả năng Crawl (Playwright)

**Mô tả vấn đề:**
- Module crawl từ web HTML đang phải giả lập (Mock). Hệ thống hiện tại mới phục vụ tốt API trả về JSON. Cần khả năng cào mạnh cho các web chống boot (Cloudflare).

**Giải pháp:**
- Code đầy đủ hàm `crawl_novel_playwright()` chạy Browser Headless.

**Các bước thực hiện:**
1. Cài Playwright trên Ubuntu/Termux.
2. Thực hiện intercept network để bypass bảo mật nếu cần.

**Checklist hoàn thành:**
- [ ] Playwright cào thành công các trang tĩnh và trang chống bot phổ biến.

---

## Task 4.6: Test Tự Động (Auto Testing)

**Mô tả vấn đề:**
- Script test rải rác, thao tác print() thủ công thay vì Assertion. Không tích hợp CI/CD.

**Giải pháp:**
- Sử dụng framework `pytest`.
- Phủ unit-test cho QTEngine, Pipeline Manager, NLP tools.

**Các bước thực hiện:**
1. Cài đặt pytest.
2. Khởi tạo folder `Test/tests/`.
3. Chuyển đổi các file `test_*.py` cũ sang format `test_..._func(mocker)`.

**Checklist hoàn thành:**
- [ ] Đạt tối thiểu 60% Test Coverage cho các core modules.

---
**TỔNG KẾT PHASE 4:** Hệ thống hoàn thiện vòng đời, đạt trạng thái tối ưu như đề án Plan.md. Chạy song song không cần can thiệp thường xuyên, cung cấp chỉ số theo dõi và hiệu năng tốt.
