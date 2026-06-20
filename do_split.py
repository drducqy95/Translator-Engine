import os
import re
from pathlib import Path

engine_dir = Path("/sdcard/my agent/Translator Engine")
bot_file = engine_dir / "telegram_bot_v2.py"
content = bot_file.read_text(encoding="utf-8")

bot_dir = engine_dir / "Bot"
bot_dir.mkdir(exist_ok=True)
(bot_dir / "daemons").mkdir(exist_ok=True)
(bot_dir / "handlers").mkdir(exist_ok=True)
(bot_dir / "utils").mkdir(exist_ok=True)

# Helper to extract functions by name
def extract_func(name, text):
    pattern = rf"def {name}\(.*?\):.*?(?=\n(?:def |@|# ==========================================|$))"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(0)
    return ""

def extract_handler(command, text):
    pattern = rf"@bot\.message_handler\(commands=\['{command}'\]\).*?(?=\n(?:@bot|def |# ==========================================|$))"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(0)
    return ""

# We will just rename telegram_bot_v2.py to Bot/main.py for now,
# but we'll extract daemons and state to make it slightly cleaner, 
# because writing a perfect full refactor script is too risky for the bot's runtime.

# Wait, instead of half-measures, let's create the config and state, and modify main.py to import them.
config_content = """import os
import logging
from pathlib import Path
import telebot
from dotenv import load_dotenv

engine_dir = Path(__file__).parent.parent
import sys
sys.path.append(str(engine_dir / 'Script'))
from source_manager import SourceManager
from user_manager import UserManager

(engine_dir / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(engine_dir / "logs" / "bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TranslatorBot")

load_dotenv(engine_dir / ".env")
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN) if TOKEN else None

source_mgr = SourceManager(str(engine_dir))
user_mgr = UserManager(engine_dir)
"""
(bot_dir / "config.py").write_text(config_content, encoding="utf-8")

print("Created config.py")

