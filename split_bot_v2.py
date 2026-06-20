import os
from pathlib import Path

engine_dir = Path("/sdcard/my agent/Translator Engine")
orig_file = engine_dir / "telegram_bot_v2.py"

lines = orig_file.read_text(encoding="utf-8").splitlines()

# Find the start of daemons
daemon_start = 0
for i, line in enumerate(lines):
    if line.startswith("def daemon_raw_processing():"):
        daemon_start = i
        break

if daemon_start == 0:
    print("Could not find daemons, aborting split.")
    exit(1)

# Extract daemons block
daemons_lines = lines[daemon_start:]
main_lines = lines[:daemon_start]

# Also remove the infinity_polling from daemons if it's there
main_loop_idx = -1
for i, line in enumerate(daemons_lines):
    if line.startswith("print(") or "infinity_polling" in line:
        main_loop_idx = i
        break

if main_loop_idx != -1:
    main_loop_lines = daemons_lines[main_loop_idx:]
    daemons_lines = daemons_lines[:main_loop_idx]
    main_lines.extend(main_loop_lines)

# Write Bot/daemons.py
(engine_dir / "Bot").mkdir(exist_ok=True)
daemons_content = "import time\nimport shutil\nfrom pathlib import Path\nimport traceback\n"
daemons_content += "from Bot.config import logger, load_settings, engine_dir, source_mgr, pinned_messages\n"
daemons_content += "from pipeline_manager import PipelineManager\n\n"
daemons_content += "\n".join(daemons_lines)
(engine_dir / "Bot" / "daemons.py").write_text(daemons_content, encoding="utf-8")

# Write Bot/config.py
config_content = """import os
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
"""
(engine_dir / "Bot" / "config.py").write_text(config_content, encoding="utf-8")

print("Created daemons.py and config.py")
