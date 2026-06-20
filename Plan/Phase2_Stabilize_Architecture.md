# KẾ HOẠCH PHASE 2: ỔN ĐỊNH — Kiến trúc & Chất lượng Code (3-5 ngày)

**Mục tiêu:** Tái cấu trúc bot từ file monolithic khổng lồ thành cấu trúc mô-đun chuẩn, dễ mở rộng, dễ quản lý. Đảm bảo trạng thái không bị mất khi khởi động lại bot.
**Thời gian ước tính:** 3-5 ngày

---

## Task 2.1: Tách `telegram_bot_v2.py` thành các modules nhỏ

**Mô tả vấn đề:**
- `telegram_bot_v2.py` dài 1204 dòng, chứa toàn bộ logic (handlers, daemon, auth, menus). Rất khó bảo trì, hàm xử lý menu chính chứa chain `if-elif` dài hơn 500 dòng.
- Import thư viện và module lặp đi lặp lại bên trong thân hàm.

**Giải pháp:**
- Cấu trúc lại mã nguồn theo chuẩn:
```
Bot/
├── __init__.py
├── main.py              # Entry point khởi chạy bot và daemon
├── config.py            # Quản lý file .env, các tham số hằng
├── state.py             # UserState (Thread-safe, Persistent)
├── admin.py             # Logic phân quyền, tải cache admins
├── handlers/
│   ├── __init__.py
│   ├── menu.py          # Command /start và menu điều hướng chính
│   ├── search.py        # Logic tìm truyện qua DuckDuckGo / AI
│   ├── reader.py        # Logic đọc truyện (navigate files)
│   ├── translate.py     # Lệnh /quick, xử lý file gửi trực tiếp
│   ├── dictionary.py    # Xử lý chỉnh sửa DB dict
│   ├── source.py        # Quản lý nguồn (plugin list, crawl request)
│   ├── pipeline.py      # Tương tác/Quản lý tiến độ dịch truyện
│   └── settings.py      # Tuỳ chỉnh hệ thống
├── daemons/
│   ├── __init__.py
│   ├── raw_processor.py # Luồng xử lý chia chương nền
│   ├── project_init.py  # Luồng khởi tạo truyện mới
│   └── pipeline_exec.py # Luồng thực thi dịch thuật
└── utils/
    ├── __init__.py
    ├── escape.py        # html_escape, md_escape (nếu còn dùng)
    └── keyboard.py      # Các hàm sinh InlineKeyboardMarkup
```

**Các bước thực hiện:**
1. Tạo cấu trúc thư mục `Bot/`.
2. Di chuyển các hàm xử lý nhỏ sang `utils/`.
3. Di chuyển hệ thống Daemon sang `daemons/`.
4. Di chuyển hàm xử lý Auth sang `admin.py`.
5. Tách chuỗi 500 dòng của hàm handler menu ra thành các handler độc lập dựa trên prefix (ví dụ: callback data bắt đầu bằng `search_` -> chuyển qua `handlers/search.py`).
6. Tạo `main.py` để register các handler vào object `bot`.

**Checklist hoàn thành:**
- [ ] Phân chia cấu trúc file/thư mục thành công.
- [ ] Code không còn các lệnh import bên trong thân hàm.
- [ ] `main.py` chạy ổn định như bot ban đầu.

---

## Task 2.2: Persistent State (Lưu trạng thái bền vững)

**Mô tả vấn đề:**
- Nếu bot sập hoặc được khởi động lại, biến dict in-memory `user_state` và `pinned_messages` mất sạch dữ liệu. Trải nghiệm người dùng sẽ bị đứt gãy.
- Hệ thống Admin load file JSON liên tục mỗi khi bot gọi `is_admin()`, lãng phí thao tác I/O trên ổ cứng.

**Giải pháp:**
- Dùng `SQLite` hoặc `JSON/Pickle` tự động flush dữ liệu xuống đĩa để duy trì trạng thái của `UserState`.
- Lưu cache cho danh sách Admin thay vì đọc file trên mỗi yêu cầu truy cập (có thể dùng Time-To-Live hoặc cập nhật vào bộ nhớ ngay sau khi file bị chỉnh sửa).

**Các bước thực hiện:**
1. Code class `PersistentState` với khả năng read/write xuống file `Temp/user_state.json`.
2. Gắn hook vào hàm shutdown và sau mỗi thao tác có thay đổi state để gọi `.save()`.
3. Thêm biến cache `admin_cache` trong `admin.py`.

**Checklist hoàn thành:**
- [ ] Bot restart xong thì trạng thái menu/lịch sử đang dùng của người dùng vẫn còn.
- [ ] Cache auth tiết kiệm I/O.

---

## Task 2.3: Error Handling & Logging nâng cao

**Mô tả vấn đề:**
- Trong bot hiện tại rải rác `except: pass`, lỗi im lặng không cảnh báo.
- Dùng `print()` thay cho `logging`.
- Các daemon khi dính exception (như bị lỗi API AI) sẽ vòng lặp vô hạn vì không có Retry Limit.

**Giải pháp:**
- Áp dụng `logging` của Python.
- Set retry counter, nếu fail quá 3 lần thì đánh dấu chương là FAILED và dừng xử lý để admin duyệt.

**Các bước thực hiện:**
1. Replace tất cả `print()` bằng `logger.info()`, `logger.error()`.
2. Thêm `except Exception as e: logger.error(f"Lỗi: {e}")`.
3. Trong các class Daemon, thêm field theo dõi số lần `retry`, nếu > 3 thì đổi trạng thái sang `ERROR`.
4. Cấu hình log xoay vòng (Log Rotate) giới hạn dung lượng log file.

**Checklist hoàn thành:**
- [ ] Log ghi ra file `/sdcard/my agent/Translator Engine/logs/`.
- [ ] Daemon không còn kẹt trong vòng lặp vô tận.

---

## Task 2.4: Dọn dẹp file thừa & File trùng lặp

**Mô tả vấn đề:**
- Hệ thống bị lẫn lộn giữa bản Bot V1 (`telegram_bot.py`) và Bot V2 (`telegram_bot_v2.py`).
- Chứa các script vá lỗi một lần (`patch_bot.py`, `patch_indent.py`) đã cũ và các script test nằm rải rác.
- Có 2 file cấu hình `ai_providers.json` và `ai_client.py` nằm trùng lặp ở Root, ở `Temp/` và ở `Script/`.
- Tồn tại file copy `translator_knowledge.db` ở gốc.

**Các bước thực hiện:**
1. Xóa (hoặc chuyển vào thư mục Archive) các file: `telegram_bot.py`, `patch_bot.py`, `patch_indent.py`, `translator_knowledge.db` ở gốc.
2. Di chuyển `test_69_search.py`, `test_ddg.py`, `test_plugin.py`, `test_qt.py` vào `Test/`.
3. Hợp nhất `ai_providers.json`, chỉ dùng file đặt tại cấu hình chuẩn `Temp/`.
4. Gỡ bỏ bản sao cũ của `ai_client.py`.

**Checklist hoàn thành:**
- [ ] Cây thư mục root sạch sẽ. Chỉ giữ lại những tệp tối thiểu.

---

## Task 2.5: Cập nhật thư viện (`requirements.txt`)

**Mô tả vấn đề:**
- Tệp `requirements.txt` không hoàn chỉnh, thiếu nhiều dependencies (ví dụ `duckduckgo_search`, `curl_cffi`, `python-dotenv`).

**Các bước thực hiện:**
1. Tạo mới tệp `requirements.txt`:
```txt
pyTelegramBotAPI>=4.14
python-dotenv>=1.0
Flask>=3.0
requests>=2.31
beautifulsoup4>=4.12
jieba>=0.42
opencc-python-reimplemented>=0.1.7
playwright>=1.40
duckduckgo_search>=4.0
curl_cffi>=0.5
```

**Checklist hoàn thành:**
- [ ] Lệnh `pip install -r requirements.txt` chạy không bị thiếu gói nào cho toàn bộ ứng dụng.

---
**TỔNG KẾT PHASE 2:** Kiến trúc sẽ trở nên gọn gàng, module hóa cao, xử lý lỗi chuyên nghiệp và an toàn trước sự cố khởi động lại.
