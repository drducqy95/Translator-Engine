from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional


class RhinoBridgeError(RuntimeError):
    pass


class RhinoBridge:
    def __init__(self, base_dir: str | Path, rhino_jar: str | Path | None = None):
        self.base_dir = Path(base_dir)
        self.rhino_jar = Path(rhino_jar) if rhino_jar else self._find_rhino_jar()
        self.java_source = self.base_dir / "Script" / "legado" / "rhino" / "LegadoRhinoBridge.java"
        self.class_dir = self.base_dir / "Dashboard" / "data" / "legado" / "state" / "rhino_classes"
        self.process: Optional[subprocess.Popen[str]] = None
        self.lock = threading.Lock()
        self.source_state: Dict[str, Any] = {}
        self.cache_state: Dict[str, Any] = {}
        self.cookie_state: Dict[str, Any] = {}
        self.book_state: Dict[str, Any] = {}
        self.chapter_state: Dict[str, Any] = {}
        self.rule_callback: Optional[Callable[[str, List[Any], Dict[str, Any]], Any]] = None

    @property
    def available(self) -> bool:
        return bool(shutil.which("java") and shutil.which("javac") and self.rhino_jar.exists() and self.java_source.exists())

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def eval(
        self,
        script: str,
        bindings: Optional[Dict[str, Any]] = None,
        scope_key: str = "default",
        js_lib: str = "",
        timeout_ms: int = 8000,
        callback_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not self.available:
            raise RhinoBridgeError("Java/Javac/Rhino jar is not available")
        self._ensure_process()
        merged_bindings = dict(bindings or {})
        merged_bindings.setdefault("sourceState", self.source_state)
        merged_bindings.setdefault("cacheState", self.cache_state)
        merged_bindings.setdefault("cookieState", self.cookie_state)
        merged_bindings.setdefault("bookState", self.book_state)
        merged_bindings.setdefault("chapterState", self.chapter_state)
        request = {
            "id": uuid.uuid4().hex,
            "op": "eval",
            "scopeKey": scope_key,
            "jsLib": js_lib or "",
            "bindings": merged_bindings,
            "script": script,
            "timeoutMs": timeout_ms,
        }
        line = json.dumps(request, ensure_ascii=False)
        with self.lock:
            assert self.process is not None and self.process.stdin and self.process.stdout
            try:
                self.process.stdin.write(line + "\n")
                self.process.stdin.flush()
                response = self._read_response(request["id"], callback_context or {})
            except BrokenPipeError as exc:
                self.process = None
                raise RhinoBridgeError("Rhino bridge process stopped") from exc
        if not response:
            self.process = None
            raise RhinoBridgeError("Rhino bridge returned no response")
        if not response.get("ok"):
            raise RhinoBridgeError(response.get("error") or "Rhino eval failed")
        state = response.get("state") or {}
        if isinstance(state.get("sourceState"), dict):
            self.source_state = state["sourceState"]
        if isinstance(state.get("cacheState"), dict):
            self.cache_state = state["cacheState"]
        if isinstance(state.get("cookieState"), dict):
            self.cookie_state = state["cookieState"]
        if isinstance(state.get("bookState"), dict):
            self.book_state = state["bookState"]
        if isinstance(state.get("chapterState"), dict):
            self.chapter_state = state["chapterState"]
        return response.get("result")

    def _read_response(self, request_id: str, callback_context: Dict[str, Any]) -> Dict[str, Any]:
        assert self.process is not None and self.process.stdin and self.process.stdout
        while True:
            raw = self.process.stdout.readline()
            if not raw:
                return {}
            message = json.loads(raw)
            if message.get("op") == "callback":
                callback_response = self._handle_callback(message, callback_context)
                self.process.stdin.write(json.dumps(callback_response, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
                continue
            if message.get("id") == request_id:
                return message

    def _handle_callback(self, message: Dict[str, Any], callback_context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not self.rule_callback:
                raise RhinoBridgeError(f"No callback handler for {message.get('name')}")
            merged = dict(callback_context)
            bindings = message.get("bindings")
            if isinstance(bindings, dict):
                merged.setdefault("bindings", bindings)
            result = self.rule_callback(str(message.get("name") or ""), list(message.get("args") or []), merged)
            return {"id": message.get("id"), "ok": True, "result": result}
        except Exception as exc:
            return {"id": message.get("id"), "ok": False, "error": str(exc)}

    def _ensure_process(self) -> None:
        self._compile_if_needed()
        if self.process and self.process.poll() is None:
            return
        cp = os.pathsep.join([str(self.class_dir), str(self.rhino_jar)])
        self.process = subprocess.Popen(
            ["java", "-cp", cp, "LegadoRhinoBridge"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(self.base_dir),
        )

    def _compile_if_needed(self) -> None:
        self.class_dir.mkdir(parents=True, exist_ok=True)
        class_file = self.class_dir / "LegadoRhinoBridge.class"
        if class_file.exists() and class_file.stat().st_mtime >= self.java_source.stat().st_mtime:
            return
        cp = str(self.rhino_jar)
        proc = subprocess.run(
            ["javac", "-encoding", "UTF-8", "-cp", cp, "-d", str(self.class_dir), str(self.java_source)],
            cwd=str(self.base_dir),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RhinoBridgeError(proc.stderr.strip() or proc.stdout.strip() or "javac failed")

    def _find_rhino_jar(self) -> Path:
        candidates = [
            self.base_dir / "Script" / "legado" / "rhino" / "rhino-1.7.14.jar",
            self.base_dir / "temp" / "legado-qt-main" / "legado-qt-main" / "modules" / "rhino" / "lib" / "rhino-1.7.14.jar",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]
