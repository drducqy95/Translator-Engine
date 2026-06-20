import os
import json
import importlib
from pathlib import Path
from plugins.base_plugin import BasePlugin
from plugins.json_plugin import JsonPlugin

class PluginManager:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.plugins = {}
        self._load_all_plugins()

    def _load_all_plugins(self):
        # 1. Load JSON plugins
        json_path = self.base_dir / "Dashboard" / "data" / "crawl_sites.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for site in data.get("sites", []):
                        site_id = site.get("id")
                        if site_id:
                            self.plugins[site_id] = JsonPlugin(site)
            except Exception as e:
                print(f"[PluginManager] Lỗi tải JSON plugins: {e}")

        # 2. Load Python plugins (override JSON if duplicated)
        plugins_dir = self.base_dir / "Script" / "plugins"
        if not plugins_dir.exists():
            return
            
        for file in plugins_dir.glob("site_*.py"):
            module_name = f"plugins.{file.stem}"
            try:
                module = importlib.import_module(module_name)
                # Find class that inherits from BasePlugin
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
                        instance = attr()
                        self.plugins[instance.source_id] = instance
            except Exception as e:
                print(f"[PluginManager] Lỗi tải plugin {file.name}: {e}")

    def get_plugin(self, source_id: str) -> BasePlugin:
        return self.plugins.get(source_id)

    def list_plugins(self):
        return [{"id": k, "name": v.source_name} for k, v in self.plugins.items()]
