import os
import json
from pathlib import Path
import time

class UserManager:
    def __init__(self, engine_dir):
        self.engine_dir = Path(engine_dir)
        self.users_dir = self.engine_dir / "Users"
        self.admin_dir = self.users_dir / "Admin"
        self.guest_dir = self.users_dir / "Guest"
        
        self.admin_dir.mkdir(parents=True, exist_ok=True)
        self.guest_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_user_dir(self, chat_id: str, is_admin: bool) -> Path:
        base_dir = self.admin_dir if is_admin else self.guest_dir
        user_dir = base_dir / str(chat_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir
        
    def init_user_profile(self, chat_id: str, is_admin: bool, username: str = ""):
        user_dir = self._get_user_dir(chat_id, is_admin)
        
        # Initialize info.json
        info_path = user_dir / "info.json"
        if not info_path.exists():
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "chat_id": chat_id,
                    "username": username,
                    "role": "admin" if is_admin else "guest",
                    "created_at": time.time(),
                    "last_interaction": time.time()
                }, f, indent=4, ensure_ascii=False)
        else:
            # Update last interaction
            try:
                with open(info_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['last_interaction'] = time.time()
                data['username'] = username or data.get('username', '')
                data['role'] = "admin" if is_admin else "guest"
                with open(info_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except:
                pass
                
        # Initialize other files
        files_to_init = {
            "memory.json": {"conversations": []},
            "persona.json": {"preferences": {}, "habits": {}},
            "reading_history.json": {"currently_reading": {}, "bookmarks": {}}
        }
        
        for filename, default_data in files_to_init.items():
            file_path = user_dir / filename
            if not file_path.exists():
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, indent=4, ensure_ascii=False)

    def update_reading_progress(self, chat_id: str, is_admin: bool, novel_id: str, chapter_file: str, page: int = 0):
        user_dir = self._get_user_dir(chat_id, is_admin)
        hist_path = user_dir / "reading_history.json"
        
        try:
            if hist_path.exists():
                with open(hist_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"currently_reading": {}, "bookmarks": {}}
                
            data["currently_reading"][novel_id] = {
                "last_chapter_file": chapter_file,
                "last_page": page,
                "updated_at": time.time()
            }
            
            with open(hist_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[UserManager] Lỗi lưu lịch sử đọc: {e}")

    def get_reading_progress(self, chat_id: str, is_admin: bool):
        user_dir = self._get_user_dir(chat_id, is_admin)
        hist_path = user_dir / "reading_history.json"
        try:
            if hist_path.exists():
                with open(hist_path, 'r', encoding='utf-8') as f:
                    return json.load(f).get("currently_reading", {})
        except:
            pass
        return {}
