import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import json
import threading
from pathlib import Path
import sys
import sqlite3

# Paths
BASE_DIR = Path("/sdcard/My Agent/Translator Engine")
TEMP_DIR = BASE_DIR / "Temp"
DASH_DATA = BASE_DIR / "Dashboard/data"
SCRIPT_DIR = BASE_DIR / "Script"
DICT_DIR = BASE_DIR / "Dict"

# Load config
try:
    with open(TEMP_DIR / "telegram_config.json", 'r', encoding='utf-8') as f:
        config = json.load(f)
    TOKEN = config['bot_token']
    CHAT_ID = str(config['chat_id'])
except Exception as e:
    print(f"Lỗi đọc telegram_config.json: {e}")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

def is_auth(obj):
    chat_id = str(obj.chat.id) if hasattr(obj, 'chat') else str(obj.message.chat.id)
    return chat_id == CHAT_ID

def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔍 Quét Truyện Mới", callback_data="cmd_scan"),
        InlineKeyboardButton("📚 Chờ Tải (Khởi Tạo)", callback_data="cmd_list"),
        InlineKeyboardButton("📊 Quản Lý Đang Dịch", callback_data="cmd_manage"),
        InlineKeyboardButton("⚙️ Thêm Từ Điển / Sửa Tên", callback_data="cmd_dict")
    )
    return markup

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    if not is_auth(message): return
    bot.reply_to(message, "🚀 *BẢNG ĐIỀU KHIỂN TRANS-CORE V2*\nHãy chọn thao tác bên dưới:", reply_markup=main_menu(), parse_mode='Markdown')

# ==========================================
# XỬ LÝ NÚT BẤM (CALLBACKS)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    if not is_auth(call): return
    data = call.data
    
    # 1. QUÉT TRUYỆN MỚI
    if data == "cmd_scan":
        bot.answer_callback_query(call.id, "Đang lùng sục web...")
        bot.send_message(CHAT_ID, "⏳ Đang chạy Playwright quét mục lục web ngầm...")
        def task():
            sys.path.append(str(BASE_DIR / "Dashboard"))
            import crawl_scanner
            try:
                res = crawl_scanner.scan_all_sites()
                new_count = len([d for d in res if d['status'] == 'discovered'])
                bot.send_message(CHAT_ID, f"✅ Quét xong! Tìm thấy {new_count} truyện mới. Nhấn [📚 Chờ Tải] ở Menu để xem.")
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ Lỗi quét: {e}")
        threading.Thread(target=task).start()
        
    # 2. DANH SÁCH CHỜ TẢI
    elif data == "cmd_list":
        disc_file = DASH_DATA / "discovered_novels.json"
        if not disc_file.exists():
            bot.answer_callback_query(call.id, "Chưa có dữ liệu, hãy Quét trước.")
            return
            
        with open(disc_file, 'r', encoding='utf-8') as f:
            novels = json.load(f)
            
        discovered = [d for d in novels if d['status'] in ('discovered', 'error')]
        if not discovered:
            bot.answer_callback_query(call.id, "Chưa có truyện mới.")
            return
            
        markup = InlineKeyboardMarkup(row_width=1)
        for d in discovered[:8]:
            btn_text = f"📥 Tải: {d['title']} ({d['site_name']})"
            # Gói gọn dữ liệu callback
            markup.add(InlineKeyboardButton(btn_text, callback_data=f"crawl|{d['id']}"))
        markup.add(InlineKeyboardButton("🔙 Menu Chính", callback_data="cmd_menu"))
        bot.edit_message_text("📚 *Danh sách truyện tìm thấy:*", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    # 3. KÍCH HOẠT TẢI & KHỞI TẠO
    elif data.startswith("crawl|"):
        novel_id = data.split("|")[1]
        
        # Tìm URL trong json
        url = None
        disc_file = DASH_DATA / "discovered_novels.json"
        with open(disc_file, 'r', encoding='utf-8') as f:
            novels = json.load(f)
        for d in novels:
            if d['id'] == novel_id:
                url = d['url']
                d['status'] = 'done' # Đánh dấu luôn
                break
        
        if not url:
            bot.answer_callback_query(call.id, "Lỗi: Không tìm thấy URL.")
            return
            
        # Cập nhật status JSON
        with open(disc_file, 'w', encoding='utf-8') as f:
            json.dump(novels, f, ensure_ascii=False, indent=2)
            
        bot.answer_callback_query(call.id, "Bắt đầu tải...")
        bot.send_message(CHAT_ID, f"🚀 Bắt đầu kéo `{novel_id}` về và tự động tạo Pipeline!", parse_mode='Markdown')
        
        def task():
            sys.path.append(str(SCRIPT_DIR))
            from source_manager import SourceManager
            mgr = SourceManager(str(BASE_DIR))
            try:
                mgr.crawl_novel_playwright(url, novel_id, max_chapters=5)
                mgr.init_novel_from_split(novel_id)
                bot.send_message(CHAT_ID, f"🎉 `{novel_id}` đã Tải & Khởi tạo xong!")
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ Lỗi tải `{novel_id}`: {e}")
        threading.Thread(target=task).start()

    # 4. QUẢN LÝ ĐANG DỊCH (CHỌN TRUYỆN)
    elif data == "cmd_manage":
        out_dir = BASE_DIR / "Output"
        if not out_dir.exists():
            bot.answer_callback_query(call.id, "Chưa có truyện nào đang dịch.")
            return
            
        novels = [d.name for d in out_dir.iterdir() if d.is_dir() and (d/"toc.json").exists()]
        if not novels:
            bot.answer_callback_query(call.id, "Chưa có truyện nào.")
            return
            
        markup = InlineKeyboardMarkup(row_width=2)
        # Nút Báo cáo tổng hợp ở trên cùng
        markup.add(InlineKeyboardButton("🌍 Báo Cáo Tổng Hợp Toàn Hệ Thống", callback_data="global_status"))
        for nv in novels:
            markup.add(InlineKeyboardButton(f"📖 {nv}", callback_data=f"manage|{nv}"))
        markup.add(InlineKeyboardButton("🔙 Menu Chính", callback_data="cmd_menu"))
        bot.edit_message_text("📊 *Quản lý truyện đang dịch:*", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    # 4.5. GLOBAL STATUS (BÁO CÁO TỔNG HỢP)
    elif data == "global_status":
        out_dir = BASE_DIR / "Output"
        novels = [d for d in out_dir.iterdir() if d.is_dir() and (d/"toc.json").exists()]
        
        if not novels:
            bot.answer_callback_query(call.id, "Không có dữ liệu.")
            return
            
        msg = "🌍 *BÁO CÁO TIẾN ĐỘ TOÀN HỆ THỐNG*\n\n"
        total_done = 0
        total_chapters = 0
        
        for d in novels:
            novel_id = d.name
            toc_path = d / "toc.json"
            try:
                with open(toc_path, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                    chapters = len(toc.get('chapters', []))
                    done = sum(1 for c in toc.get('chapters', []) if c.get('status') == 'done')
                    total_done += done
                    total_chapters += chapters
                    
                    # Tính %
                    percent = round((done / chapters) * 100, 1) if chapters > 0 else 0
                    
                    msg += f"🔹 *{novel_id}*: {done}/{chapters} chương ({percent}%)\n"
            except:
                msg += f"🔹 *{novel_id}*: Lỗi đọc dữ liệu\n"
                
        msg += f"\n📈 *TỔNG CỘNG:* Đã dịch {total_done}/{total_chapters} chương."
        bot.answer_callback_query(call.id)
        bot.send_message(CHAT_ID, msg, parse_mode='Markdown')

    # 5. MENU CON CỦA 1 TRUYỆN
    elif data.startswith("manage|"):
        novel_id = data.split("|")[1]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📈 Báo Cáo Tiến Độ", callback_data=f"status|{novel_id}"),
            InlineKeyboardButton("▶️ Dịch Chương Kế Tiếp", callback_data=f"process|{novel_id}"),
            InlineKeyboardButton("📦 Xuất Ebook (Epub)", callback_data=f"export|{novel_id}"),
            InlineKeyboardButton("📄 Nhận File Config", callback_data=f"get|{novel_id}|config"),
            InlineKeyboardButton("🔙 Chọn Truyện Khác", callback_data="cmd_manage")
        )
        bot.edit_message_text(f"⚙️ *Menu Truyện:* `{novel_id}`", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    # 6. STATUS
    elif data.startswith("status|"):
        novel_id = data.split("|")[1]
        out_dir = BASE_DIR / "Output" / novel_id
        toc_path = out_dir / "toc.json"
        timeline_path = out_dir / "story_timeline.json"
        msg = f"📊 *Trạng thái:* `{novel_id}`\n\n"
        try:
            with open(toc_path, 'r', encoding='utf-8') as f:
                toc = json.load(f)
                total = len(toc['chapters'])
                done = sum(1 for c in toc['chapters'] if c['status'] == 'done')
                msg += f"📈 Tiến độ: *{done}/{total}* chương.\n"
                pending = [c['file'] for c in toc['chapters'] if c['status'] == 'pending']
                if pending: msg += f"⏭️ Chương tiếp theo: `{pending[0]}`\n"
        except: msg += "Lỗi đọc TOC.\n"
        try:
            with open(timeline_path, 'r', encoding='utf-8') as f:
                timeline = json.load(f)
                if timeline:
                    last_event = timeline[-1]
                    msg += f"\n*Sự kiện gần nhất ({last_event['chapter']}):*\n_{last_event.get('summary', {}).get('main_events', 'N/A')}_"
        except: pass
        bot.answer_callback_query(call.id)
        bot.send_message(CHAT_ID, msg, parse_mode='Markdown')

    # 7. PROCESS NEXT CHAPTER
    elif data.startswith("process|"):
        novel_id = data.split("|")[1]
        out_dir = BASE_DIR / "Output" / novel_id
        try:
            with open(out_dir / "toc.json", 'r', encoding='utf-8') as f:
                toc = json.load(f)
            pending = [c['file'] for c in toc['chapters'] if c['status'] == 'pending']
            if not pending:
                bot.answer_callback_query(call.id, "Truyện đã dịch xong tất cả!")
                return
            chap_file = pending[0]
            bot.answer_callback_query(call.id, f"Kích hoạt dịch {chap_file}")
            bot.send_message(CHAT_ID, f"⚙️ Đang kích hoạt Pipeline xử lý: `{chap_file}`...")
            def task():
                sys.path.append(str(SCRIPT_DIR))
                from pipeline_manager import PipelineManager
                mgr = PipelineManager(novel_id, str(BASE_DIR / "Source_Split" / novel_id), str(out_dir))
                if mgr.process_chapter(chap_file, start_stage=1):
                    bot.send_message(CHAT_ID, f"✅ Đã dịch xong `{chap_file}`!")
                else:
                    bot.send_message(CHAT_ID, f"❌ Lỗi khi dịch `{chap_file}`. Hãy kiểm tra Logs.")
            threading.Thread(target=task).start()
        except Exception as e:
            bot.answer_callback_query(call.id, f"Lỗi: {e}")

    # 8. EXPORT
    elif data.startswith("export|"):
        novel_id = data.split("|")[1]
        bot.answer_callback_query(call.id, "Đang đóng gói...")
        bot.send_message(CHAT_ID, f"📚 Đang nén truyện `{novel_id}` thành Ebook...")
        def task():
            sys.path.append(str(SCRIPT_DIR))
            import novel_exporter
            try:
                files = novel_exporter.export_novel(str(BASE_DIR / "Output" / novel_id))
                for f in files:
                    if f.suffix == '.epub':
                        with open(f, 'rb') as doc:
                            bot.send_document(CHAT_ID, doc, caption=f"Ebook: {f.name}")
                        break
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ Lỗi Export: {e}")
        threading.Thread(target=task).start()

    # 9. GET CONFIG
    elif data.startswith("get|"):
        parts = data.split("|")
        novel_id = parts[1]
        bot.answer_callback_query(call.id)
        target_file = BASE_DIR / "Output" / novel_id / "translation_config.json"
        if target_file.exists():
            with open(target_file, 'rb') as f:
                bot.send_document(CHAT_ID, f, caption=f"Cấu hình của `{novel_id}`")
        else:
            bot.send_message(CHAT_ID, "❌ Không tìm thấy config file.")

    # 10. DICTIONARY MENU
    elif data == "cmd_dict":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(CHAT_ID, "✍️ *Nhập dữ liệu Từ điển mới*\n\nHãy nhập nội dung tin nhắn dưới dạng:\n`<tên_truyện> | <từ_gốc> | <từ_dịch> | <loại>`\n\n*(Ví dụ: novel_1 | 姬诚 | Cơ Thành | character)*\n\nGõ chữ 'Hủy' để thoát.", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_dict_input)

    # 11. MENU CHÍNH
    elif data == "cmd_menu":
        bot.edit_message_text("🚀 *BẢNG ĐIỀU KHIỂN TRANS-CORE V2*", call.message.chat.id, call.message.message_id, reply_markup=main_menu(), parse_mode="Markdown")

# XỬ LÝ NHẬP TỪ ĐIỂN TỪ NGƯỜI DÙNG
def process_dict_input(message):
    if not is_auth(message): return
    if message.text.lower() == 'hủy':
        bot.send_message(CHAT_ID, "Đã hủy thao tác.")
        return
        
    parts = [p.strip() for p in message.text.split('|')]
    if len(parts) < 4:
        bot.send_message(CHAT_ID, "⚠️ Sai cú pháp. Thao tác bị hủy. Hãy bấm lại nút Thêm Từ Điển.")
        return
        
    novel_id = parts[0]
    raw = parts[1]
    target = parts[2]
    ent_type = parts[3]
    
    db_name = "global.db" if novel_id.lower() == "global" else f"project_{novel_id}.db"
    db_path = DICT_DIR / db_name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS dict_entries (key TEXT PRIMARY KEY, target TEXT, type TEXT)")
        conn.execute("INSERT OR REPLACE INTO dict_entries (key, target, type) VALUES (?, ?, ?)", (raw, target, ent_type))
        conn.commit()
        conn.close()
        bot.send_message(CHAT_ID, f"✅ Đã Khóa Từ: `{raw}` -> `{target}` ({ent_type})\nTrong Database: `{db_name}`", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ Lỗi DB: {e}")

# XỬ LÝ NHẬN FILE TXT / JSON
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if not is_auth(message): return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        
        if file_name.endswith('.txt'):
            bot.reply_to(message, f"✅ Đã nhận file Truyện Raw: `{file_name}`.\nĐang tự động Cắt chương (Split) và Khởi tạo Hệ thống...", parse_mode='Markdown')
            def task():
                save_path = BASE_DIR / "Source_Full" / file_name
                save_path.parent.mkdir(exist_ok=True)
                with open(save_path, 'wb') as new_file:
                    new_file.write(downloaded_file)
                sys.path.append(str(SCRIPT_DIR))
                from source_manager import SourceManager
                mgr = SourceManager(str(BASE_DIR))
                novel_id = file_name.replace('.txt', '').replace(' ', '_').lower()
                try:
                    mgr.split_and_init_novel(novel_id, file_name)
                    bot.send_message(CHAT_ID, f"🎉 Đã Khởi tạo Truyện xong!\nNovel ID: `{novel_id}`", parse_mode='Markdown')
                except Exception as e:
                    bot.send_message(CHAT_ID, f"❌ Lỗi tách chương: {e}")
            threading.Thread(target=task).start()
            
        elif file_name == 'translation_config.json':
            novel_id = message.caption
            if not novel_id:
                bot.reply_to(message, "⚠️ Xin hãy Upload lại và ghi tên `<novel_id>` vào phần Caption (chú thích).")
                return
            target_dir = BASE_DIR / "Output" / novel_id
            if not target_dir.exists():
                bot.reply_to(message, f"❌ Không tìm thấy truyện `{novel_id}`.")
                return
            with open(target_dir / "translation_config.json", 'wb') as f:
                f.write(downloaded_file)
            bot.reply_to(message, f"✅ Đã đè thành công Config mới cho truyện `{novel_id}`.")
            
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: {e}")

if __name__ == '__main__':
    print("🤖 Telegram Orchestrator V3 (Inline UI) đang chạy... Chờ lệnh từ sếp.")
    # Xóa webhook cũ (nếu có) để tránh lỗi 409 Conflict
    bot.remove_webhook()
    bot.polling(non_stop=True)
