import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sys
import logging
import threading
import time
from pathlib import Path
import json
import os
import html
from dotenv import load_dotenv

def md_escape(text):
    """Escape các ký tự đặc biệt cho Markdown V1."""
    if not text: return ""
    text = str(text)
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, '\\' + ch)
    return text

# Thêm đường dẫn để import các module cốt lõi
engine_dir = Path(__file__).parent
(engine_dir / "logs").mkdir(exist_ok=True)

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(engine_dir / "logs" / "bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TranslatorBot")
sys.path.append(str(engine_dir / 'Script'))
from source_manager import SourceManager
from pipeline_manager import PipelineManager
from plugin_manager import PluginManager
from user_manager import UserManager

# Tải cấu hình Bot
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("WARNING: BOT_TOKEN is not set in .env")
bot = telebot.TeleBot(TOKEN)

# Đăng ký Slash Commands trên Telegram Menu
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Hiển thị menu chính"),
    telebot.types.BotCommand("/search", "Tìm truyện trên mạng"),
    telebot.types.BotCommand("/read", "Đọc truyện đã dịch"),
    telebot.types.BotCommand("/cancel", "Hủy bỏ thao tác hiện tại"),
    telebot.types.BotCommand("/quick", "Dịch nhanh (File/Văn bản)"),
    telebot.types.BotCommand("/crawl", "Quản lý tiến trình Crawl"),
    telebot.types.BotCommand("/sources", "Quản lý Nguồn Truyện"),
    telebot.types.BotCommand("/raw", "Kho Truyện Raw"),
    telebot.types.BotCommand("/translate", "Quản lý Dịch Truyện"),
    telebot.types.BotCommand("/progress", "Tiến độ chung"),
    telebot.types.BotCommand("/settings", "Cài đặt Hệ thống"),
    telebot.types.BotCommand("/admin", "Khu vực Quản trị viên"),
])

# Khởi tạo core managers
source_mgr = SourceManager(str(engine_dir))
user_mgr = UserManager(engine_dir)

# State của user: lưu ngữ cảnh đang ở menu nào
user_state = {}
state_lock = threading.Lock()

# Pinned message data
pinned_messages = {} # novel_id -> message_id
pinned_lock = threading.Lock()

def load_persistent_state():
    global user_state, pinned_messages
    try:
        p1 = engine_dir / "Temp" / "user_state.json"
        if p1.exists():
            with open(p1, 'r', encoding='utf-8') as f:
                user_state = json.load(f)
        p2 = engine_dir / "Temp" / "pinned_messages.json"
        if p2.exists():
            with open(p2, 'r', encoding='utf-8') as f:
                pinned_messages = json.load(f)
    except Exception as e:
        logger.error(f"Error loading state: {e}")

def save_persistent_state():
    try:
        with state_lock:
            with open(engine_dir / "Temp" / "user_state.json", 'w', encoding='utf-8') as f:
                json.dump(user_state, f, ensure_ascii=False)
        with pinned_lock:
            with open(engine_dir / "Temp" / "pinned_messages.json", 'w', encoding='utf-8') as f:
                json.dump(pinned_messages, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def daemon_state_saver():
    while True:
        time.sleep(60)
        save_persistent_state()

load_persistent_state()
threading.Thread(target=daemon_state_saver, daemon=True).start()


admin_cache = None

def load_admins():
    global admin_cache
    if admin_cache: return admin_cache
    path = engine_dir / "Temp" / "admins.json"
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                admin_cache = json.load(f)
                return admin_cache
        except Exception as e: logger.error(f"Error loading admins: {e}")
    return {"master": None, "admins": []}

def save_admins(data):
    global admin_cache
    admin_cache = data
    path = engine_dir / "Temp" / "admins.json"
    path.parent.mkdir(exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def is_admin(chat_id):
    adm = load_admins()
    if adm.get("master") == chat_id:
        return True
    if chat_id in adm.get("admins", []):
        return True
    return False

def check_access(chat_id, require_admin=True):
    adm = load_admins()
    if adm.get("master") is None:
        adm["master"] = chat_id
        save_admins(adm)
        user_mgr.init_user_profile(str(chat_id), True)
        bot.send_message(chat_id, "👑 **Chào Sếp lớn!** Hệ thống đã tự động ghi nhận ngài là **MASTER ADMIN** rồi nhé. Mọi quyền lực giờ nằm trong tay sếp!", parse_mode="Markdown")
        return True
        
    if require_admin and not is_admin(chat_id):
        user_mgr.init_user_profile(str(chat_id), is_admin(chat_id))
        bot.send_message(chat_id, "⛔️ **Ây da!** Tính năng này bảo mật lắm, chỉ có Sếp (Admin) mới xài được thôi ạ.")
        return False
        
    user_mgr.init_user_profile(str(chat_id), is_admin(chat_id))
    return True

def load_settings():
    path = engine_dir / "Temp" / "settings.json"
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"daemon_raw": True, "daemon_init": True, "daemon_pipeline": True}

def save_settings(settings):
    path = engine_dir / "Temp" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def trigger_auto_debug(chat_id, err_desc):
    bot.send_message(chat_id, f"🚀 **Kích hoạt AGY Auto-Debug!**\n\n**Mô tả lỗi:** {md_escape(err_desc)}\n\nAGY Agent đang được khởi chạy ngầm. Quá trình phân tích, sửa lỗi và restart bot có thể mất 3-10 phút. Bạn sẽ nhận được báo cáo khi hoàn tất.", parse_mode="Markdown")
    import subprocess
    prompt = f"User reported system error in Translator Engine: '{md_escape(err_desc)}'. Please analyze the logs, fix the python code in '/sdcard/My Agent/Translator Engine/', and then restart the telegram bot (telegram_bot_v2.py). Finally, send a detailed report via Telegram to chat_id {chat_id}."
    cmd = ["agy", "--print-timeout", "30m", "-p", prompt]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Không thể khởi chạy AGY: {e}")

# ==========================================
# GIAO DIỆN CHÍNH (MAIN MENU)
# ==========================================
def create_main_menu(is_adm=False):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔍 Tìm Truyện", callback_data="menu_search"),
        InlineKeyboardButton("📖 Đọc Truyện", callback_data="menu_read")
    )
    markup.add(
        InlineKeyboardButton("⚡ Dịch Nhanh", callback_data="menu_quick")
    )
    if is_adm:
        markup.add(
            InlineKeyboardButton("🕸 Quản lý Crawl", callback_data="menu_crawl_mgr"),
            InlineKeyboardButton("📚 Quản lý Nguồn", callback_data="menu_sources")
        )
        markup.add(
            InlineKeyboardButton("📂 Kho Truyện Raw", callback_data="menu_raw"),
            InlineKeyboardButton("🌐 Quản lý Dịch", callback_data="menu_translation")
        )
        markup.add(
            InlineKeyboardButton("📊 Tiến độ chung", callback_data="menu_progress"),
            InlineKeyboardButton("⚙️ Cài đặt Hệ thống", callback_data="menu_settings")
        )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    check_access(chat_id, require_admin=False)
    is_adm = is_admin(chat_id)
    welcome_text = (
        "🤖 **Chào mừng Sếp đến với Trạm Điều Hành V2!**\n\n"
        "Em đã nổ máy, lên đồ sẵn sàng. Hệ thống đa luồng và dịch thuật tự động đang miệt mài chạy ngầm rồi ạ.\n"
        "Sếp muốn em làm gì tiếp theo cứ chọn menu bên dưới nhé 👇"
    )
    bot.send_message(chat_id, welcome_text, reply_markup=create_main_menu(is_adm), parse_mode="Markdown")

@bot.message_handler(commands=['search'])
def cmd_search(message):
    bot.send_message(message.chat.id, "🔍 Sếp muốn tìm bộ truyện nào? Cứ gõ tên (Việt hay Trung đều được) để em đi lùng cho:")
    user_state[message.chat.id] = {'step': 'waiting_search_query'}

@bot.message_handler(commands=['read'])
def cmd_read(message):
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "⏳ Sếp chờ chút xíu, em đang lục tủ sách...")
    call = type('obj', (object,), {'id': '0', 'message': msg, 'data': 'menu_read'})
    try: handle_menu_read(chat_id, call)
    except Exception as e: bot.edit_message_text(f"Lỗi: {e}", chat_id, msg.message_id)

@bot.message_handler(commands=['quick'])
def cmd_quick(message):
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "⏳ Đang tải...")
    call = type('obj', (object,), {'id': '0', 'message': msg, 'data': 'menu_quick'})
    try: handle_menu(call)
    except Exception as e: bot.edit_message_text(f"Lỗi: {e}", chat_id, msg.message_id)

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    chat_id = message.chat.id
    if not check_access(chat_id, require_admin=True): return
    bot.send_message(chat_id, "🛠 **KHU VỰC QUẢN TRỊ**", reply_markup=create_main_menu(is_adm=True), parse_mode="Markdown")

def simulate_admin_command(message, data):
    chat_id = message.chat.id
    if not check_access(chat_id, require_admin=True): return
    msg = bot.send_message(chat_id, "⏳ Đang tải...")
    call = type('obj', (object,), {'id': '0', 'message': msg, 'data': data})
    try: handle_menu(call)
    except Exception as e: 
        if "query is too old" not in str(e): # Ignore fake callback id errors
            bot.edit_message_text(f"Lỗi: {e}", chat_id, msg.message_id)

@bot.message_handler(commands=['crawl'])
def cmd_crawl(message): simulate_admin_command(message, "menu_crawl_mgr")

@bot.message_handler(commands=['sources'])
def cmd_sources(message): simulate_admin_command(message, "menu_sources")

@bot.message_handler(commands=['raw'])
def cmd_raw(message): simulate_admin_command(message, "menu_raw")

@bot.message_handler(commands=['translate'])
def cmd_translate(message): simulate_admin_command(message, "menu_translation")

@bot.message_handler(commands=['progress'])
def cmd_progress(message): simulate_admin_command(message, "menu_progress")

@bot.message_handler(commands=['settings'])
def cmd_settings(message): simulate_admin_command(message, "menu_settings")

# ==========================================
# CALLBACK HANDLERS (ĐIỀU HƯỚNG MENU)
# ==========================================

def handle_menu_read(chat_id, call):
    out_dir = engine_dir / "Output"
    projects = []
    if out_dir.exists():
        for pdir in out_dir.iterdir():
            if pdir.is_dir() and (pdir / "State" / "toc.json").exists():
                try:
                    with open(pdir / "State" / "toc.json", 'r', encoding='utf-8') as f:
                        toc = json.load(f)
                    done = sum(1 for c in toc.get('chapters', []) if c.get('status') == 'done')
                    if done > 0:
                        projects.append(pdir.name)
                except: pass
                
    if not projects:
        try: bot.answer_callback_query(call.id, "Tủ sách hiện tại trống trơn Sếp ạ. Chưa có truyện nào dịch xong cả.", show_alert=True)
        except: bot.send_message(chat_id, "Tủ sách hiện tại trống trơn Sếp ạ. Chưa có truyện nào dịch xong cả.")
        return
        
    markup = InlineKeyboardMarkup(row_width=1)
    
    # 1. Truyện đang đọc dở
    reading_history = user_mgr.get_reading_progress(str(chat_id), is_admin(chat_id))
    if reading_history:
        # Lọc ra những truyện vẫn tồn tại trong list projects
        valid_history = {k: v for k, v in reading_history.items() if k in projects}
        if valid_history:
            # Sắp xếp theo updated_at mới nhất
            sorted_hist = sorted(valid_history.items(), key=lambda x: x[1].get('updated_at', 0), reverse=True)
            for p_id, p_data in sorted_hist[:3]: # Lấy 3 truyện đọc gần nhất
                last_chap = p_data.get('last_chapter_file', '')
                if last_chap:
                    # Rút gọn tên file để hiển thị
                    chap_disp = last_chap.replace('.md', '')
                    if len(chap_disp) > 20: chap_disp = chap_disp[:20] + "..."
                    markup.add(InlineKeyboardButton(f"▶️ Tiếp tục: {p_id[:15]}... ({chap_disp})", callback_data=f"readchap||{p_id}||{last_chap}"))
    
    # 2. Danh sách toàn bộ truyện
    for p in projects:
        markup.add(InlineKeyboardButton(f"📖 {p}", callback_data=f"readproj||{p}||0"))
        
    markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
    bot.edit_message_text("📚 **Sếp muốn đọc bộ nào đây?** Chọn ở dưới nhé:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_menu(call):
    chat_id = call.message.chat.id
    data = call.data
    
    # KIỂM TRA QUYỀN ADMIN CHO CÁC TÍNH NĂNG NHẠY CẢM
    public_actions = ["menu_search", "menu_read", "menu_main", "menu_quick", "quick_"]
    is_public = any(data.startswith(a) for a in public_actions) or data.startswith("readproj||") or data.startswith("readchap||") or data.startswith("searchcrawl_")
    
    if not is_public and not is_admin(chat_id):
        bot.answer_callback_query(call.id, "⛔️ Bạn không có quyền Admin để dùng tính năng này.", show_alert=True)
        return
        
    # --- PUBLIC FEATURES ---
    if data == "menu_search":
        bot.send_message(chat_id, "🔍 Nhập tên truyện cần tìm (Tiếng Việt hoặc Trung):")
        user_state[chat_id] = {'step': 'waiting_search_query'}
        bot.answer_callback_query(call.id)
        
    elif data == "menu_read":
        handle_menu_read(chat_id, call)

    elif data.startswith("readproj||"):
        parts = data.split("||")
        novel_id = parts[1]
        page = int(parts[2])
        
        toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
        if not toc_path.exists(): return
        with open(toc_path, 'r', encoding='utf-8') as f:
            toc = json.load(f)
            
        done_chaps = [c for c in toc.get('chapters', []) if c.get('status') == 'done']
        total = len(done_chaps)
        start_idx = page * 10
        chaps = done_chaps[start_idx:start_idx+10]
        
        markup = InlineKeyboardMarkup(row_width=1)
        for c in chaps:
            t_file = c.get('translated_file', c.get('name'))
            markup.add(InlineKeyboardButton(t_file, callback_data=f"readchap||{novel_id}||{t_file}"))
            
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"readproj||{novel_id}||{page-1}"))
        if start_idx + 10 < total: nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"readproj||{novel_id}||{page+1}"))
        if nav: markup.row(*nav)
        
        markup.add(InlineKeyboardButton("🔙 Danh sách truyện", callback_data="menu_read"))
        escaped_novel_id = novel_id.replace("_", "\\_").replace("*", "\\*")
        bot.edit_message_text(f"📖 **{escaped_novel_id}** (Trang {page+1})\nChọn chương để đọc:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("readchap||"):
        parts = data.split("||")
        novel_id = parts[1]
        chap_file = parts[2]
        chap_path = engine_dir / "Output" / novel_id / "Final_Translated" / chap_file
        if chap_path.exists():
            with open(chap_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Tách nội dung nếu quá 4000 ký tự (Giới hạn của Telegram)
            for i in range(0, len(content), 4000):
                bot.send_message(chat_id, content[i:i+4000])
            bot.answer_callback_query(call.id, "Đã gửi chương.")
            # Lưu lịch sử
            user_mgr.update_reading_progress(str(chat_id), is_admin(chat_id), novel_id, chap_file)
        else:
            bot.answer_callback_query(call.id, "Lỗi: Không tìm thấy file chương.", show_alert=True)

    elif data == "menu_quick":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("📄 Dịch File (TXT, EPUB, DOCX...)", callback_data="quick_file"))
        markup.add(InlineKeyboardButton("📝 Dịch Đoạn Văn Bản", callback_data="quick_text"))
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
        bot.edit_message_text("⚡ **Dịch Nhanh:**\nTính năng mở rộng dành cho tất cả mọi người (hoạt động độc lập hoặc gộp vào hệ thống chính).", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "quick_file":
        bot.send_message(chat_id, "📁 Sếp ném file truyện vào đây cho em nhé (hỗ trợ `.txt`, `.epub`, `.docx`, `.md`, `.html` nha).\n\nEm sẽ nhét nó vào kho `Source_Full` rồi tự động băm nhỏ ra dịch ngay tắp lự!", parse_mode="Markdown")
        user_state[chat_id] = {'step': 'waiting_quick_file'}

    elif data == "quick_text":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("✍️ Nhập văn bản (Dùng Prompt hiện tại)", callback_data="quick_text_input"))
        markup.row(
            InlineKeyboardButton("🇨🇳 Trung -> Việt", callback_data="quick_lang_zh_vi"),
            InlineKeyboardButton("🇬🇧 Anh -> Việt", callback_data="quick_lang_en_vi")
        )
        markup.row(
            InlineKeyboardButton("🇻🇳 Việt -> Anh", callback_data="quick_lang_vi_en"),
            InlineKeyboardButton("🇯🇵 Nhật -> Việt", callback_data="quick_lang_ja_vi")
        )
        markup.add(InlineKeyboardButton("⚙️ Tùy chỉnh Prompt Dịch (Gọi LLM tự do)", callback_data="quick_text_prompt"))
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_quick"))
        bot.edit_message_text("📝 **Xử Lý Văn Bản Đa Ngôn Ngữ:**\nBạn có thể chọn nhanh ngôn ngữ dịch hoặc tự viết Prompt tùy chỉnh để gọi LLM giải quyết mọi yêu cầu xử lý văn bản.", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("quick_lang_"):
        lang_map = {
            "zh_vi": "Dịch đoạn văn bản tiếng Trung sau sang tiếng Việt chuẩn, trau chuốt câu từ:",
            "en_vi": "Dịch đoạn văn bản tiếng Anh sau sang tiếng Việt, giữ nguyên ý nghĩa và ngữ cảnh:",
            "vi_en": "Translate the following Vietnamese text to English with natural phrasing:",
            "ja_vi": "Dịch đoạn văn bản tiếng Nhật sau sang tiếng Việt tự nhiên và chính xác:"
        }
        lang_key = data.replace("quick_lang_", "")
        prompt = lang_map.get(lang_key, "")
        if prompt:
            user_state.setdefault(chat_id, {})
            user_state[chat_id]['custom_prompt'] = prompt
            bot.send_message(chat_id, f"✅ Bơm Prompt xong rồi Sếp ơi:\n`{md_escape(prompt)}`\n\n✍️ Giờ Sếp ném đoạn văn bản cần xử lý vào đây đi:", parse_mode="Markdown")
            user_state[chat_id]['step'] = 'waiting_quick_text'

    elif data == "quick_text_input":
        prompt = user_state.get(chat_id, {}).get('custom_prompt', "Dịch đoạn văn bản tiếng Trung sau sang tiếng Việt theo văn phong tiểu thuyết, chuẩn cấu trúc ngữ pháp:")
        bot.send_message(chat_id, f"⚙️ Mâm bát đã dọn sẵn với Prompt: `{md_escape(prompt)}`\n\n✍️ Sếp quăng văn bản vào cho em xử nào:", parse_mode="Markdown")
        user_state[chat_id]['step'] = 'waiting_quick_text'

    elif data == "quick_text_prompt":
        current_prompt = user_state.get(chat_id, {}).get('custom_prompt', "Dịch đoạn văn bản tiếng Trung sau sang tiếng Việt theo văn phong tiểu thuyết, chuẩn cấu trúc ngữ pháp:")
        bot.send_message(chat_id, f"⚙️ **Prompt cũ đang là thế này:**\n`{md_escape(current_prompt)}`\n\nSếp nhắn cho em Prompt mới đi (Ví dụ: `Tóm tắt ngắn gọn đoạn này` hoặc `Dịch sang tiếng Anh`), đổi ý thì gõ `/cancel` nhé:", parse_mode="Markdown")
        user_state[chat_id]['step'] = 'waiting_quick_prompt'

    # --- ADMIN FEATURES ---
    # 1. QUẢN LÝ NGUỒN TRUYỆN
    elif data == "menu_sources":
        try:
            with open(engine_dir / "Dashboard/data/crawl_sites.json", 'r', encoding='utf-8') as f:
                sites = json.load(f).get('sites', [])
            markup = InlineKeyboardMarkup(row_width=1)
            for s in sites:
                markup.add(InlineKeyboardButton(f"{s['name']}", callback_data=f"source_{s['id']}"))
            markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
            bot.edit_message_text("🌐 **Danh sách Nguồn Crawl:**\nChọn một nguồn để xem list truyện cập nhật.", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Lỗi: {e}")

    elif data.startswith("source_"):
        site_id = data.replace("source_", "")
        bot.edit_message_text(f"⏳ Đang tải danh sách chuyên mục từ web...", chat_id, call.message.message_id)
        
        def fetch_cats():
            try:
                cats = source_mgr.get_site_categories(site_id)
                if not cats:
                    bot.edit_message_text("❌ Không tìm thấy chuyên mục nào.", chat_id, call.message.message_id)
                    return
                
                # Dịch thô tên chuyên mục
                from qt_engine import QTEngine
                qt = QTEngine()
                for c in cats:
                    c['name_vi'] = qt.translate(c['name'])[0]
                
                # Lưu vào state
                user_state[chat_id] = {'site_id': site_id, 'cats': cats}
                
                markup = InlineKeyboardMarkup(row_width=2)
                for i, c in enumerate(cats[:20]): # Limit 20
                    name_vi = c.get('name_vi', c['name'])
                    markup.add(InlineKeyboardButton(name_vi, callback_data=f"cat_{i}"))
                markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_sources"))
                
                bot.edit_message_text(f"📑 **Chuyên mục của {md_escape(site_id)}:**", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                bot.edit_message_text(f"❌ Lỗi: {e}", chat_id, call.message.message_id)
        threading.Thread(target=fetch_cats).start()

    elif data.startswith("cat_"):
        idx = int(data.replace("cat_", ""))
        state = user_state.get(chat_id, {})
        site_id = state.get('site_id')
        cats = state.get('cats', [])
        if not site_id or idx >= len(cats):
            bot.answer_callback_query(call.id, "Session hết hạn, vui lòng thao tác lại.")
            return
            
        cat_url = cats[idx]['url']
        cat_name = cats[idx].get('name_vi', cats[idx]['name'])
        bot.edit_message_text(f"⏳ Đang cào danh sách truyện từ mục: {md_escape(cat_name)}...", chat_id, call.message.message_id)
        
        def fetch_novels():
            try:
                novels = source_mgr.get_novels_from_category(site_id, cat_url)
                if not novels:
                    bot.edit_message_text("❌ Không tìm thấy truyện nào.", chat_id, call.message.message_id)
                    return
                
                # Dịch thô tên truyện
                from qt_engine import QTEngine
                qt = QTEngine()
                for n in novels:
                    n['title_vi'] = qt.translate(n['title'])[0]
                    n['author_vi'] = qt.translate(n['author'])[0]
                
                user_state[chat_id]['novels'] = novels
                
                markup = InlineKeyboardMarkup(row_width=1)
                for i, n in enumerate(novels[:10]):
                    title = n.get('title_vi', n['title'])
                    markup.add(InlineKeyboardButton(f"{title} ({n.get('author_vi', '')})", callback_data=f"selnov_{i}"))
                markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data=f"source_{site_id}"))
                
                bot.edit_message_text(f"🔥 **Top Truyện ({md_escape(cat_name)}):**\nBấm vào truyện để thêm vào Hàng đợi Crawl tự động.", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                bot.edit_message_text(f"❌ Lỗi: {e}", chat_id, call.message.message_id)
        threading.Thread(target=fetch_novels).start()

    elif data.startswith("selnov_"):
        idx = int(data.replace("selnov_", ""))
        novels = user_state.get(chat_id, {}).get('novels', [])
        site_id = user_state.get(chat_id, {}).get('site_id')
        if idx >= len(novels):
            return
        novel = novels[idx]
        # Thêm vào Plan Crawl
        bot.send_message(chat_id, f"✅ Đã thêm **{md_escape(novel['title'])}** vào danh sách Crawl tự động.\nHệ thống sẽ tải ngầm toàn bộ chương.", parse_mode="Markdown")
        # TODO: Trigger Crawl Daemon for this URL

    # 2. KHO TRUYỆN RAW
    elif data == "menu_raw":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("Truyện Full", callback_data="raw_full"),
            InlineKeyboardButton("Truyện Split (Chia chương)", callback_data="raw_split")
        )
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
        bot.edit_message_text("📂 **Kho Truyện Raw:**\nQuản lý file text gốc chưa qua dịch thuật.", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        
    elif data == "raw_full":
        source_full = engine_dir / "Source_Full"
        dirs = [d.name for d in source_full.iterdir() if d.is_dir()] if source_full.exists() else []
        msg = "📁 **Các truyện đã tải Full:**\n" + "\n".join(f"- `{d}`" for d in dirs) if dirs else "Chưa có truyện nào trong Source_Full."
        bot.edit_message_text(msg, chat_id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_raw")), parse_mode="Markdown")

    elif data == "raw_split":
        source_split = engine_dir / "Source_Split"
        dirs = [d.name for d in source_split.iterdir() if d.is_dir()] if source_split.exists() else []
        msg = "📁 **Các truyện đã được Split:**\n" + "\n".join(f"- `{d}`" for d in dirs) if dirs else "Chưa có truyện nào trong Source_Split."
        bot.edit_message_text(msg, chat_id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_raw")), parse_mode="Markdown")

    elif data == "menu_crawl_mgr":
        bot.edit_message_text("🕸 **Quản lý Crawl:**\nTính năng này đang được phát triển...", chat_id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main")), parse_mode="Markdown")

    elif data.startswith("searchcrawl_"):
        idx = int(data.replace("searchcrawl_", ""))
        url = user_state.get(chat_id, {}).get(f'search_res_{idx}')
        if url:
            bot.send_message(chat_id, f"✅ Đã nhận lệnh tải từ: {url}\nChức năng Crawl tự động đang được phát triển...", parse_mode="Markdown")
            
    elif data == "noop":
        bot.answer_callback_query(call.id)

    # 3. QUẢN LÝ DỊCH TRUYỆN
    elif data.startswith("menu_translation"):
        page = 0
        if "page_" in data:
            page = int(data.split("_")[-1])
            
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🔍 Tìm Truyện Dịch", callback_data="search_translation"))
        
        # Quét các dự án đang có trong Output
        out_dir = engine_dir / "Output"
        if out_dir.exists():
            projects = [d for d in out_dir.iterdir() if d.is_dir() and (d / "State" / "toc.json").exists()]
        else:
            projects = []
            
        if not projects:
            markup.add(InlineKeyboardButton("Chưa có dự án nào.", callback_data="noop"))
        else:
            projects.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            project_names = [p.name for p in projects]
            
            start_idx = page * 10
            for p in project_names[start_idx:start_idx+10]:
                markup.add(InlineKeyboardButton(f"📘 {p}", callback_data=f"proj||{p}"))
                
            nav = []
            if page > 0: nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"menu_translation_page_{page-1}"))
            if start_idx + 10 < len(project_names): nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"menu_translation_page_{page+1}"))
            if nav: markup.row(*nav)
                
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
        bot.edit_message_text("🌐 **Quản lý Dịch Truyện:**\nChọn đầu truyện để quản lý Database, Từ điển và Tiến độ.", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "search_translation":
        bot.send_message(chat_id, "🔍 Nhập từ khóa tên truyện dịch cần tìm:")
        user_state[chat_id] = {'step': 'waiting_search_translation'}

    elif data.startswith("proj||"):
        novel_id = data.replace("proj||", "")
        user_state[chat_id] = {'novel_id': novel_id}
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📊 Báo cáo Tiến độ", callback_data=f"prog||{novel_id}"),
            InlineKeyboardButton("🔄 Dịch lại chương", callback_data=f"retrans||{novel_id}")
        )
        markup.add(
            InlineKeyboardButton("🧑 Character DB", callback_data=f"db||{novel_id}||char||0"),
            InlineKeyboardButton("📖 Glossary DB", callback_data=f"db||{novel_id}||glos||0")
        )
        markup.add(
            InlineKeyboardButton("⚙️ Translator Config", callback_data=f"tcfg||{novel_id}"),
            InlineKeyboardButton("⏱️ Story Timeline", callback_data=f"time||{novel_id}")
        )
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_translation"))
        
        bot.edit_message_text(f"🛠 **Quản lý Dự án: {md_escape(novel_id)}**\nChọn tính năng cần thao tác:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("db||"):
        # Format: db||{md_escape(novel_id)}||{type}||{page}
        parts = data.split("||")
        if len(parts) >= 4:
            novel_id = parts[1]
            db_type = parts[2]
            page = int(parts[3])
            
            bot.edit_message_text(f"⏳ Đang tải từ điển {db_type} trang {page}...", chat_id, call.message.message_id)
            
            def load_db():
                try:
                    import sqlite3
                    db_path = engine_dir / "Dict" / f"project_{novel_id}.db"
                    if not db_path.exists():
                        bot.edit_message_text(f"❌ Từ điển project_{md_escape(novel_id)}.db chưa được tạo.", chat_id, call.message.message_id)
                        return
                    
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("SELECT key, target FROM dict_entries WHERE type=?", (db_type,))
                    all_entries = cur.fetchall()
                    conn.close()
                    
                    total = len(all_entries)
                    start_idx = page * 10
                    entries = all_entries[start_idx:start_idx+10]
                    
                    user_state[chat_id]['db_cache'] = entries
                    user_state[chat_id]['db_info'] = {'novel': novel_id, 'type': db_type, 'page': page}
                    
                    markup = InlineKeyboardMarkup(row_width=1)
                    if not entries:
                        markup.add(InlineKeyboardButton("Chưa có từ khóa nào.", callback_data="noop"))
                    else:
                        for i, (key, target) in enumerate(entries):
                            markup.add(InlineKeyboardButton(f"{md_escape(key)} ➔ {md_escape(target)}", callback_data=f"edkw_{i}"))
                            
                    # Nav buttons
                    nav = []
                    if page > 0:
                        nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"db||{novel_id}||{db_type}||{page-1}"))
                    if start_idx + 10 < total:
                        nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"db||{novel_id}||{db_type}||{page+1}"))
                    if nav:
                        markup.row(*nav)
                        
                    markup.add(InlineKeyboardButton("🔙 Quay lại Dự án", callback_data=f"proj||{novel_id}"))
                    bot.edit_message_text(f"📖 **Từ điển {db_type.upper()} ({md_escape(novel_id)})**\nTrang {page+1} (Tổng: {total} từ)\nBấm vào một dòng để chỉnh sửa:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
                except Exception as e:
                    bot.edit_message_text(f"❌ Lỗi: {e}", chat_id, call.message.message_id)
            threading.Thread(target=load_db).start()

    elif data.startswith("edkw_"):
        idx = int(data.replace("edkw_", ""))
        cache = user_state.get(chat_id, {}).get('db_cache', [])
        info = user_state.get(chat_id, {}).get('db_info', {})
        if idx >= len(cache):
            return
        
        key, target = cache[idx]
        user_state[chat_id]['step'] = 'waiting_db_edit'
        user_state[chat_id]['edit_key'] = key
        
        bot.send_message(chat_id, f"✏️ **Sửa nghĩa cho từ:** `{md_escape(key)}`\nNghĩa cũ: `{md_escape(target)}`\n\n👉 Vui lòng nhắn tin nghĩa mới vào khung chat (hoặc gõ /cancel để hủy):", parse_mode="Markdown")

    elif data.startswith("prog||"):
        novel_id = data.replace("prog||", "")
        toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
        if toc_path.exists():
            try:
                with open(toc_path, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                chaps = toc.get('chapters', [])
                total = len(chaps)
                done = sum(1 for c in chaps if c.get('status') == 'done')
                pending = total - done
                msg = f"📊 **Tiến Độ Dự Án: {md_escape(novel_id)}**\n\n"
                msg += f"✅ Đã dịch: {done} chương\n"
                msg += f"⏳ Đang chờ: {pending} chương\n"
                msg += f"📈 Hoàn thành: {int((done/total)*100) if total else 0}%\n"
                bot.edit_message_text(msg, chat_id, call.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Quay lại", callback_data=f"proj||{novel_id}")))
            except Exception as e:
                bot.answer_callback_query(call.id, f"Lỗi đọc TOC: {e}")
        else:
            bot.answer_callback_query(call.id, "Không tìm thấy file toc.json")

    elif data.startswith("tcfg||"):
        novel_id = data.replace("tcfg||", "")
        cfg_path = engine_dir / "Output" / novel_id / "State" / "translation_config.json"
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            goal = cfg.get("translation_goal", {})
            style = goal.get("style", "")
            bot.send_message(chat_id, f"⚙️ **Translator Config ({md_escape(novel_id)})**\n\n**Style hiện tại:**\n{style}\n\n👉 Nhắn tin nội dung Style mới (hoặc /cancel):", parse_mode="Markdown")
            user_state[chat_id]['step'] = 'waiting_tcfg_edit'
            user_state[chat_id]['edit_novel'] = novel_id
        else:
            bot.answer_callback_query(call.id, "Chưa có file config")

    elif data.startswith("time||"):
        novel_id = data.replace("time||", "")
        time_path = engine_dir / "Output" / novel_id / "State" / "story_timeline.json"
        if time_path.exists():
            with open(time_path, 'r', encoding='utf-8') as f:
                timeline = json.load(f)
            if not timeline:
                bot.send_message(chat_id, f"⏱️ **Story Timeline ({md_escape(novel_id)})**\nChưa có sự kiện nào.")
            else:
                msg = f"⏱️ **Story Timeline ({md_escape(novel_id)}) - 10 Sự kiện gần nhất:**\n\n"
                for ev in timeline[-10:]:
                    msg += f"🔹 **{ev.get('chapter', '')}**: {ev.get('summary', {}).get('main_events', '')}\n"
                bot.send_message(chat_id, msg, parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "Chưa có timeline")

    elif data.startswith("retrans||"):
        novel_id = data.replace("retrans||", "")
        bot.send_message(chat_id, f"🔄 **Dịch lại chương ({md_escape(novel_id)})**\n👉 Nhập chính xác tên file chương (VD: `Chapter 0001.md`) để hệ thống chạy lại (Tự động bỏ qua các Stage đã pass):", parse_mode="Markdown")
        user_state[chat_id]['step'] = 'waiting_retrans'
        user_state[chat_id]['edit_novel'] = novel_id

    # 4. TIẾN ĐỘ CHUNG
    elif data == "menu_progress":
        bot.answer_callback_query(call.id, "Đang tổng hợp tiến độ...")
        out_dir = engine_dir / "Output"
        if out_dir.exists():
            msg = "📊 **Tiến Độ Các Dự Án Đang Chạy:**\n\n"
            for pdir in out_dir.iterdir():
                if pdir.is_dir() and (pdir / "State" / "toc.json").exists():
                    with open(pdir / "State" / "toc.json", 'r', encoding='utf-8') as f:
                        toc = json.load(f)
                    chaps = toc.get('chapters', [])
                    total = len(chaps)
                    done = sum(1 for c in chaps if c.get('status') == 'done')
                    msg += f"📘 **{pdir.name}**: {done}/{total} chương ({int(done/total*100) if total else 0}%)\n"
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
            bot.edit_message_text(msg, chat_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 5. CÀI ĐẶT
    elif data == "menu_settings":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("⚙️ Quản lý Tiến trình (Daemons)", callback_data="menu_daemons"))
        markup.add(InlineKeyboardButton("🐛 Tự động Gỡ lỗi (Auto-Debug)", callback_data="menu_debug"))
        markup.add(InlineKeyboardButton("👥 Gắn Admin (Chỉ Master)", callback_data="set_admin"))
        markup.add(InlineKeyboardButton("➕ Bổ sung Nguồn Crawl", callback_data="set_source"))
        markup.add(InlineKeyboardButton("🔑 Cập nhật API Key", callback_data="set_api"))
        markup.add(InlineKeyboardButton("🔙 Quay lại", callback_data="menu_main"))
        bot.edit_message_text("⚙️ **Cài Đặt Hệ Thống:**", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "set_admin":
        if load_admins().get("master") != chat_id:
            bot.answer_callback_query(call.id, "Chỉ Master Admin mới được dùng chức năng này!", show_alert=True)
            return
        bot.send_message(chat_id, "👥 **Gắn Admin Mới**\nVui lòng nhập Chat ID của người dùng cần cấp quyền:")
        user_state[chat_id]['step'] = 'waiting_new_admin'

    elif data == "menu_daemons":
        settings = load_settings()
        markup = InlineKeyboardMarkup(row_width=1)
        r_state = "🟢 ĐANG BẬT" if settings.get("daemon_raw", True) else "🔴 ĐÃ TẮT"
        i_state = "🟢 ĐANG BẬT" if settings.get("daemon_init", True) else "🔴 ĐÃ TẮT"
        p_state = "🟢 ĐANG BẬT" if settings.get("daemon_pipeline", True) else "🔴 ĐÃ TẮT"
        markup.add(InlineKeyboardButton(f"Raw Processing: {r_state}", callback_data="toggle_raw"))
        markup.add(InlineKeyboardButton(f"Project Init: {i_state}", callback_data="toggle_init"))
        markup.add(InlineKeyboardButton(f"Pipeline Executor: {p_state}", callback_data="toggle_pipeline"))
        markup.add(InlineKeyboardButton("🔙 Quay lại Cài đặt", callback_data="menu_settings"))
        bot.edit_message_text("⚙️ **Quản lý Tiến trình (Daemons)**\nBấm để Bật/Tắt tiến trình tự động:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("toggle_"):
        daemon_name = data.replace("toggle_", "")
        settings = load_settings()
        key = f"daemon_{daemon_name}"
        settings[key] = not settings.get(key, True)
        save_settings(settings)
        # Tạo lại event ảo để quay về menu_daemons
        call.data = "menu_daemons"
        handle_menu(call)

    elif data == "menu_debug":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("1. Báo cáo nhảy cóc chương", callback_data="debug_skip"))
        markup.add(InlineKeyboardButton("2. Báo cáo lỗi dịch AI", callback_data="debug_ai"))
        markup.add(InlineKeyboardButton("3. Báo cáo bot treo/đứng", callback_data="debug_hang"))
        markup.add(InlineKeyboardButton("✍️ Nhập mô tả lỗi tự do", callback_data="debug_custom"))
        markup.add(InlineKeyboardButton("🔙 Quay lại Cài đặt", callback_data="menu_settings"))
        bot.edit_message_text("🐛 **Hệ thống Auto-Debug (Self-Healing)**\nHệ thống sẽ gọi AGY Agent (Antigravity) phân tích log và tự sửa code. Chọn phân loại lỗi:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("debug_"):
        err_type = data.replace("debug_", "")
        if err_type == "custom":
            bot.send_message(chat_id, "✍️ **Mô tả lỗi:**\nVui lòng nhắn tin mô tả chi tiết lỗi bạn gặp phải (hoặc gõ /cancel):")
            user_state[chat_id]['step'] = 'waiting_debug_desc'
        else:
            err_map = {
                "skip": "Pipeline bỏ qua chương, không dịch hoặc lưu đè dữ liệu",
                "ai": "Lỗi format JSON hoặc chất lượng dịch của AI không ổn định",
                "hang": "Tiến trình ngầm bị treo, không thấy thông báo chạy mới"
            }
            trigger_auto_debug(chat_id, err_map.get(err_type, "Lỗi không xác định"))

    elif data == "set_api":
        bot.send_message(chat_id, "🔑 **Cập nhật API Key**\nNhập theo cú pháp: `[Tên_Provider] | [Base_URL] | [API_Key] | [Model]`\nVD: `gemini | https://... | sk-... | gemini-1.5-pro`", parse_mode="Markdown")
        user_state[chat_id]['step'] = 'waiting_api_key'
        
    elif data == "set_source":
        bot.send_message(chat_id, "➕ **Bổ sung Nguồn Crawl**\nNhập URL trang chủ của web truyện (VD: `https://www.biquge.tv/`):")
        user_state[chat_id]['step'] = 'waiting_new_source'

    elif data == "menu_main":
        is_adm = is_admin(chat_id)
        bot.edit_message_text("🤖 **Translator Engine V2 - TỔNG TRẠM ĐIỀU HÀNH**\n\nVui lòng chọn tính năng:", chat_id, call.message.message_id, reply_markup=create_main_menu(is_adm), parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if text == '/cancel':
        if chat_id in user_state and 'step' in user_state[chat_id]:
            del user_state[chat_id]['step']
        bot.send_message(chat_id, "Đã hủy thao tác hiện tại.")
        return
        
    state = user_state.get(chat_id, {})
    step = state.get('step')
    
    # XỬ LÝ PUBLIC INPUTS
    if step == 'waiting_search_query':
        query = text
        del user_state[chat_id]['step']
        bot.send_message(chat_id, f"🔍 Đang dịch và tìm kiếm: `{md_escape(query)}`...", parse_mode="Markdown")
        
        import threading
        def do_search():
            import ai_client
            try:
                cn_query = ai_client.call_ai(f"Translate this novel title to Chinese: '{query}'. ONLY output the Chinese text, nothing else.", timeout=15)
            except:
                cn_query = query
            
            bot.send_message(chat_id, f"✨ Đang quét từ khóa: `{md_escape(cn_query)}`...", parse_mode="Markdown")
            
            try:
                from duckduckgo_search import DDGS
                ddgs = DDGS()
                results = []
                search_term = f"{cn_query} site:69shuba.cx OR site:shuhaige.net OR site:uukanshu.cc OR site:sto.cx OR site:ptwxz.com"
                for r in ddgs.text(search_term, max_results=5):
                    results.append(r)
                    
                if not results:
                    bot.send_message(chat_id, "❌ Không tìm thấy kết quả phù hợp.")
                    return
                    
                markup = telebot.types.InlineKeyboardMarkup()
                for i, r in enumerate(results):
                    title = r.get('title', '')[:30]
                    url = r.get('href', '')
                    with state_lock:
                        if chat_id not in user_state:
                            user_state[chat_id] = {}
                    user_state[chat_id][f'search_res_{i}'] = url
                    markup.add(telebot.types.InlineKeyboardButton(f"📘 {title}", callback_data=f"searchcrawl_{i}"))
                bot.send_message(chat_id, "✅ Kết quả tìm kiếm (Bấm để Cào):", reply_markup=markup)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Lỗi tìm kiếm: {e}")
        
        threading.Thread(target=do_search, daemon=True).start()
        return

    if step == 'waiting_search_translation':
        projects_dir = engine_dir / "Output"
        if not projects_dir.exists():
            bot.send_message(chat_id, "❌ Chưa có dự án dịch nào.")
            if 'step' in user_state.get(chat_id, {}): del user_state[chat_id]['step']
            return
            
        matches = []
        for d in projects_dir.iterdir():
            if d.is_dir() and text.lower() in d.name.lower():
                matches.append(d.name)
                
        if not matches:
            bot.send_message(chat_id, f"❌ Không tìm thấy dự án nào chứa từ khóa `{md_escape(text)}`", parse_mode="Markdown")
            if 'step' in user_state.get(chat_id, {}): del user_state[chat_id]['step']
            return
            
        markup = InlineKeyboardMarkup(row_width=1)
        for m in matches[:10]:
            markup.add(InlineKeyboardButton(f"📘 {m}", callback_data=f"proj||{m}"))
        bot.send_message(chat_id, f"🔍 Kết quả tìm kiếm cho `{md_escape(text)}`:", reply_markup=markup, parse_mode="Markdown")
        if 'step' in user_state.get(chat_id, {}): del user_state[chat_id]['step']
        return

    if step == 'waiting_db_edit':
        info = state.get('db_info', {})
        novel_id = info.get('novel')
        db_type = info.get('type')
        key = state.get('edit_key')
        
        if not novel_id or not key:
            bot.send_message(chat_id, "❌ Session lỗi. Vui lòng thao tác lại từ Menu.")
            return
            
        try:
            import sqlite3
            db_path = engine_dir / "Dict" / f"project_{novel_id}.db"
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("UPDATE dict_entries SET target=? WHERE key=? AND type=?", (text, key, db_type))
            conn.commit()
            conn.close()
            
            bot.send_message(chat_id, f"✅ Đã cập nhật:\n`{md_escape(key)}` ➔ `{md_escape(text)}`", parse_mode="Markdown")
            
            # Quay lại trang từ điển trước đó
            page = info.get('page', 0)
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"Quay lại trang {page+1}", callback_data=f"db||{novel_id}||{db_type}||{page}"))
            bot.send_message(chat_id, "Bấm để quay lại từ điển:", reply_markup=markup)
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Lỗi ghi DB: {e}")
            
        del user_state[chat_id]['step']

    elif step == 'waiting_tcfg_edit':
        novel_id = state.get('edit_novel')
        if not novel_id: return
        cfg_path = engine_dir / "Output" / novel_id / "State" / "translation_config.json"
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if "translation_goal" not in cfg: cfg["translation_goal"] = {}
            cfg["translation_goal"]["style"] = text
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
            bot.send_message(chat_id, "✅ Đã lưu Style dịch thuật mới.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Lỗi ghi config: {e}")
        del user_state[chat_id]['step']

    elif step == 'waiting_retrans':
        novel_id = state.get('edit_novel')
        chap_name = text
        if not novel_id: return
        # Xóa file chapter trong các thư mục Stage (trừ Stage 0_Raw và Stage 1_Extracted để ép chạy lại từ Stage 2 hoặc Stage tương ứng nếu logic PipelineManager hỗ trợ partial re-run)
        # Tuy nhiên, cách an toàn nhất là đánh dấu chapter đó là 'pending' trong toc.json, và Pipeline sẽ tự chạy lại, skip các file JSON đã tồn tại (hoặc ta có thể xóa các artifact lỗi)
        # Vì yêu cầu là "dịch lại chỉ ảnh hưởng segment bị lỗi", tức là chạy lại Stage 3/4. Ta sẽ xóa artifact của stage 3,4.
        try:
            bot.send_message(chat_id, f"✅ Đã nhận lệnh dịch lại `{chap_name}`. Hệ thống sẽ tự phân tích và dịch bù các Segment lỗi ở chu kỳ tiếp theo.")
            # TODO: Cập nhật TOC status thành 'pending'
            toc_path = engine_dir / "Output" / novel_id / "State" / "toc.json"
            if toc_path.exists():
                with open(toc_path, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                for c in toc.get('chapters', []):
                    if c.get('file', c.get('name')) == chap_name:
                        c['status'] = 'pending'
                with open(toc_path, 'w', encoding='utf-8') as f:
                    json.dump(toc, f, ensure_ascii=False, indent=4)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Lỗi: {e}")
        del user_state[chat_id]['step']

    elif step == 'waiting_api_key':
        parts = [p.strip() for p in text.split('|')]
        if len(parts) >= 3:
            name, base_url, key = parts[:3]
            model = parts[3] if len(parts) > 3 else ""
            api_path = engine_dir / "Temp" / "ai_providers.json"
            try:
                providers = []
                if api_path.exists():
                    with open(api_path, 'r', encoding='utf-8') as f:
                        providers = json.load(f)
                providers.append({"name": name, "base_url": base_url, "api_key": key, "model_name": model})
                with open(api_path, 'w', encoding='utf-8') as f:
                    json.dump(providers, f, ensure_ascii=False, indent=4)
                bot.send_message(chat_id, "✅ Đã thêm API Provider mới.")
            except Exception as e:
                bot.send_message(chat_id, f"❌ Lỗi lưu API: {e}")
        else:
            bot.send_message(chat_id, "❌ Sai cú pháp. Vui lòng thử lại.")
        del user_state[chat_id]['step']
        
    elif step == 'waiting_new_source':
        url = text
        site_path = engine_dir / "Dashboard/data/crawl_sites.json"
        try:
            with open(site_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            new_id = "site_" + str(int(time.time()))
            config['sites'].append({
                "id": new_id,
                "name": new_id,
                "catalog_url": url,
                "selectors": {"novel_item": "li", "title": "a", "author": ".author"},
                "crawl_selectors": {"chapter_list": "a", "chapter_title": "text", "chapter_content": "div"}
            })
            with open(site_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            bot.send_message(chat_id, "✅ Đã thêm Nguồn web mới (cấu hình mặc định). Sẽ cần tinh chỉnh Selector sau.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Lỗi thêm nguồn: {e}")
        del user_state[chat_id]['step']

    elif step == 'waiting_debug_desc':
        trigger_auto_debug(chat_id, text)
        del user_state[chat_id]['step']

    elif step == 'waiting_new_admin':
        try:
            new_id = int(text.strip())
            adm = load_admins()
            if new_id not in adm.get("admins", []):
                adm.setdefault("admins", []).append(new_id)
                save_admins(adm)
                bot.send_message(chat_id, f"✅ Đã cấp quyền Admin cho Chat ID: {new_id}")
            else:
                bot.send_message(chat_id, "Chat ID này đã là Admin.")
        except:
            bot.send_message(chat_id, "❌ Chat ID không hợp lệ.")
        del user_state[chat_id]['step']

    elif step == 'waiting_quick_prompt':
        user_state[chat_id]['custom_prompt'] = text
        del user_state[chat_id]['step']
        bot.send_message(chat_id, "✅ Đã lưu cấu hình Prompt mới. Bạn có thể bắt đầu dịch văn bản.")

    elif step == 'waiting_quick_text':
        prompt = user_state.get(chat_id, {}).get('custom_prompt', "Dịch đoạn văn bản tiếng Trung sau sang tiếng Việt theo văn phong tiểu thuyết, chuẩn cấu trúc ngữ pháp:")
        full_prompt = f"{prompt}\n\n{text}"
        if 'step' in user_state.get(chat_id, {}): del user_state[chat_id]['step']
        msg = bot.send_message(chat_id, "⏳ Đang gọi AI xử lý...")
        
        # Chạy trong thread để không block bot
        def process_ai():
            try:
                import sys
import logging
                sys.path.append(str(engine_dir / "Script"))
                from ai_client import call_ai
                
                result = call_ai(full_prompt)
                for i in range(0, len(result), 4000):
                    bot.send_message(chat_id, result[i:i+4000])
                bot.delete_message(chat_id, msg.message_id)
            except Exception as e:
                bot.edit_message_text(f"❌ Lỗi AI: {e}", chat_id, msg.message_id)
                
        import threading
        threading.Thread(target=process_ai).start()

@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    if not check_access(chat_id, require_admin=False): return
    
    state = user_state.get(chat_id, {})
    if state.get('step') == 'waiting_quick_file':
        try:
            file_info = bot.get_file(message.document.file_id)
            valid_exts = ['.txt', '.html', '.epub', '.docx', '.md']
            if not any(file_info.file_path.lower().endswith(ext) for ext in valid_exts):
                bot.send_message(chat_id, f"❌ Hệ thống chỉ hỗ trợ các định dạng: {', '.join(valid_exts)}")
                return
                
            bot.send_message(chat_id, "⏳ Đang tải file về máy chủ...")
            downloaded_file = bot.download_file(file_info.file_path)
            
            raw_dir = engine_dir / "Source_Full"
            raw_dir.mkdir(exist_ok=True)
            
            save_path = raw_dir / message.document.file_name
            with open(save_path, 'wb') as new_file:
                new_file.write(downloaded_file)
                
            bot.send_message(chat_id, f"✅ Đã lưu file `{message.document.file_name}` vào kho Source_Full.\nHệ thống Daemon sẽ tự động phân chương và xử lý dịch thuật.", parse_mode="Markdown")
            del user_state[chat_id]['step']
        except Exception as e:
            bot.send_message(chat_id, f"❌ Lỗi tải file: {e}")

# ==========================================
# BACKGROUND DAEMONS (CRON JOBS)
# ==========================================
def update_pinned_progress(novel_id, status_msg):
    master_id = load_admins().get("master")
    if not master_id: return
    chat_id = master_id
    
    msg_id = pinned_messages.get(novel_id)
    # Use HTML to avoid markdown _ parsing errors in novel_id
    text = f"📌 <b>DỰ ÁN LIVE: {html.escape(novel_id)}</b>\n\n{status_msg}"
    if msg_id:
        try:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            m = bot.send_message(chat_id, text, parse_mode="HTML")
            bot.pin_chat_message(chat_id, m.message_id)
            pinned_messages[novel_id] = m.message_id
        except Exception as e:
            print(f"Lỗi ghim tin nhắn: {e}")

from Bot.daemons import daemon_raw_processing, daemon_project_init, daemon_pipeline_executor
print("🚀 TỔNG TRẠM ĐIỀU HÀNH (Dashboard V2) đang chạy...")
bot.infinity_polling()