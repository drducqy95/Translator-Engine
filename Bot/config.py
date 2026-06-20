import os
import json
import threading
import logging
from pathlib import Path
import telebot
from dotenv import load_dotenv

engine_dir = Path(__file__).parent.parent
import sys
sys.path.append(str(engine_dir / 'Script'))
from source_manager import SourceManager
from user_manager import UserManager

logger = logging.getLogger("TranslatorBot")

load_dotenv(engine_dir / ".env")
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN) if TOKEN else None

source_mgr = SourceManager(str(engine_dir))
user_mgr = UserManager(engine_dir)

user_state = {}
state_lock = threading.Lock()
pinned_messages = {}
pinned_lock = threading.Lock()

def load_settings():
    path = engine_dir / "Temp" / "settings.json"
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"daemon_raw": True, "daemon_init": True, "daemon_pipeline": True}
