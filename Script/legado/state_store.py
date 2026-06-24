from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class LegadoStateStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.state_dir = self.base_dir / "Dashboard" / "data" / "legado" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_json(self, name: str) -> Dict[str, Any]:
        path = self.state_dir / name
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_json(self, name: str, data: Dict[str, Any]) -> None:
        path = self.state_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
