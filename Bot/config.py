import os
import json
import threading
import logging
from pathlib import Path

engine_dir = Path(__file__).parent.parent
import sys
sys.path.append(str(engine_dir / 'Script'))
from source_manager import SourceManager
from user_manager import UserManager

logger = logging.getLogger("TranslatorBot")

def load_env_file(path: Path):
    """Load simple KEY=VALUE lines without requiring python-dotenv at import time."""
    try:
        from dotenv import load_dotenv
        load_dotenv(path)
        return
    except ImportError:
        pass

    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip(chr(34)).strip(chr(39))
            os.environ.setdefault(key, value)

load_env_file(engine_dir / ".env")
TOKEN = os.getenv("BOT_TOKEN")

source_mgr = SourceManager(str(engine_dir))
user_mgr = UserManager(engine_dir)

from Bot.shared_state import user_state, state_lock, pinned_messages, pinned_lock

def load_settings():
    path = engine_dir / "Temp" / "settings.json"
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"daemon_raw": True, "daemon_crawl": True, "daemon_init": True, "daemon_pipeline": True}
