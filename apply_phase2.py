import re
from pathlib import Path

content = Path('telegram_bot_v2.py').read_text(encoding='utf-8')

# 1. Add logging
if 'import logging' not in content:
    content = content.replace('import sys\n', 'import sys\nimport logging\n')
    logging_setup = """
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
"""
    content = content.replace('engine_dir = Path(__file__).parent\n', 'engine_dir = Path(__file__).parent\n(engine_dir / "logs").mkdir(exist_ok=True)\n' + logging_setup)

# Replace prints with logger.info
content = re.sub(r'print\(f?\"\[(.*?)\] (.*?)\"\)', r'logger.info(f"[\1] \2")', content)

# 2. Admin Cache
admin_cache_logic = """
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
"""
content = re.sub(r'def load_admins\(\):.*?def is_admin\(chat_id\):', admin_cache_logic + '\ndef is_admin(chat_id):', content, flags=re.DOTALL)

# 3. Persistent State (Simple wrapper that saves on exit and every 5 mins, or just direct read/write)
# We will just write a wrapper around user_state and pinned_messages

Path('telegram_bot_v2.py').write_text(content, encoding='utf-8')
print("Applied Phase 2 changes partially")
