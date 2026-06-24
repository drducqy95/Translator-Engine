# Kế Hoạch Triển Khai Chi Tiết (Implementation Plan)

Dưới đây là kế hoạch chi tiết từng dòng code và logic sẽ được thay đổi cho các Phase còn lại (Phase 1 -> Phase 4), nhằm đảm bảo tính an toàn và minh bạch trước khi thực thi.

---

## 🔒 Phase 1: Vá Lỗi Logic & Bảo Mật (Bug Fix & Security)

**Mục tiêu:** Xử lý triệt để các lỗ hổng bảo mật (lộ API Key, XSS) và các bug logic tiềm ẩn gây lỗi runtime.

### 1. Xử lý API Key & Lỗ hổng bảo mật
- **`ai_providers.json`**: Xóa cứng chuỗi API Key (`sk-...`) khỏi file. Đổi giá trị `api_key` thành chuỗi rỗng `""`.
- **`Script/ai_client.py`**: Chỉnh sửa hàm `load_providers()` để nó tự động đọc API Key từ `os.getenv("AI_API_KEY")` (từ file `.env`) thay vì lấy từ file json.
- **`.gitignore`**: Thêm `ai_providers.json`, `*.log`, `.vscode/`, `.idea/` để tránh lộ file cấu hình lên git.
- **`telegram_bot_v2.py`**: Sửa lỗi hàm `waiting_api_key` (dòng ~1004) đang ghi nhầm API key vào `Temp/ai_providers.json`. Sẽ đổi thành ghi thẳng vào file `ai_providers.json` ở thư mục gốc để đồng bộ.

### 2. Xử lý Lỗi Logic (Bug Fixes)
- **`telegram_bot_v2.py` (Lỗi Admin Cache)**:
  - Hiện tại: `if admin_cache: return admin_cache` (Lỗi khi cache là dict rỗng `{}`).
  - Sửa thành: `if admin_cache is not None: return admin_cache`.
- **`telegram_bot_v2.py` (Lỗi Index Out of Range)**:
  - Sửa các đoạn callback `data.split("||")` (như `readproj`, `db`, v.v.). Thêm bước kiểm tra độ dài mảng (ví dụ: `if len(parts) < 3: return`) trước khi truy xuất `parts[1]`, `parts[2]` để tránh `IndexError` khi có callback rác.
- **`Script/qt_engine.py` (Lỗi getattr conn)**:
  - Hàm `close(self)` đang gọi `self.conn.close()` trong khi class này không sở hữu `conn`.
  - Sửa thành: Gọi `self.dict_mgr.close()` thay vì `self.conn`.
- **`Script/stage3_ai_refiner.py` (Lỗi System Prompt)**:
  - Ở dòng ~100, code đang gộp chung `system_prompt` và `user_prompt` làm một chuỗi rồi gửi cho AI.
  - Sửa thành: Tách riêng tham số `call_ai(user_prompt, system_prompt=sys_prompt)` để LLM hiểu rõ role và tiết kiệm token.

### 3. Xử lý Web Dashboard Security
- **`Dashboard/app.py`**: Đổi `debug=True` thành `debug=False` trong `app.run()`. Thêm một decorator `@basic_auth_required` đơn giản để chặn truy cập trái phép vào route `/`.
- **`Dashboard/templates/index.html`**: Đổi các đoạn Javascript dùng `element.innerHTML = novel.title` thành `element.textContent = novel.title` để chống lỗi bảo mật XSS.

---

## 🏗️ Phase 2: Ổn Định Kiến Trúc (Stabilize Architecture)

**Mục tiêu:** Chấm dứt tình trạng "Hybrid state" (state bị trùng lặp) do quá trình refactor bỏ dở của Dev trước đó.

### 1. Dọn dẹp mã nguồn rác
- Tạo thư mục `Archive/refactor_scripts/`.
- Di chuyển 5 file refactor đang bỏ dở ở root vào đó: `apply_phase2.py`, `clean_imports.py`, `do_split.py`, `rewrite_main.py`, `split_bot_v2.py`. Việc này ngăn chặn nguy cơ ai đó chạy nhầm và ghi đè mất `telegram_bot_v2.py`.

### 2. Centralize State (Tập trung biến toàn cục)
- Xóa các biến trùng lặp khỏi `Bot/config.py` (`user_state`, `pinned_messages`, v.v.).
- Tạo một file mới `Bot/shared_state.py` làm Source of Truth duy nhất chứa: `user_state`, `state_lock`, `pinned_messages`, `pinned_lock`, `admin_cache`.
- Import các state này vào cả `telegram_bot_v2.py` và `Bot/daemons.py` để tất cả các luồng (thread) đều đọc/ghi vào cùng một ô nhớ duy nhất.

---

## ⚙️ Phase 3: An Toàn Đa Luồng (Thread Safety)

**Mục tiêu:** Khắc phục lỗi Race Condition có thể làm hỏng dữ liệu khi nhiều user hoặc nhiều daemon cùng truy xuất.

### 1. Quản lý user_state an toàn
- Trong `telegram_bot_v2.py`, hiện tại các handler như `handle_text` gán trực tiếp `user_state[chat_id] = ...` mà không giữ lock.
- Triển khai: Sẽ dùng hàm setter/getter như `set_user_state(chat_id, key, value)` và `get_user_state(chat_id, key)`. Bên trong hàm này sẽ có khối `with state_lock:`.

### 2. Dictionary Cache Lock
- Trong `Script/dict_manager.py`, mảng `_GLOBAL_DICT_CACHE` có lock khi load dữ liệu, nhưng lại KHÔNG có lock khi đọc (truy xuất từ cache). Sẽ thêm biến `_READ_LOCK` (hoặc `threading.RLock()`) bọc quanh các logic truy xuất.

---

## 🧹 Phase 4: Dọn Dẹp & Cải Thiện Chất Lượng (Quality & Cleanup)

**Mục tiêu:** Tối ưu hóa dữ liệu đầu ra và hoàn thiện tính năng.

### 1. Khắc phục lỗi "Duplicate Translations"
- Trong thư mục `Output/.../Final_Translated/`, do hệ thống dịch lại chương bị lỗi mà không xóa file cũ, dẫn tới mỗi chương có hàng chục bản sao (ví dụ: `Chapter 98` có 8 bản).
- Triển khai: Sửa file `Script/stage4_post_process.py` -> Trước khi ghi file `.md` bản dịch mới, quét thư mục `Final_Translated`, dùng regex tìm các file có cùng `Chapter XXXX` và xóa hết file cũ.

### 2. Sửa lỗi Test Script
- File `Script/test_script.py` đang báo lỗi vì unpack 3 biến cho một hàm trả về 4 biến.
- Sửa lại: `draft, cov, unk_entities, known_entities = qt.translate(seg)`.

### 3. Sửa lỗi `novel_exporter.py`
- Sửa lệnh đọc file bị rò rỉ bộ nhớ (không đóng file handle): Đổi `open(path).read()` thành `with open(path) as f: f.read()`.
