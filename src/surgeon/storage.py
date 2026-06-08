from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Union


class TraceStore:
    """Tiny JSON trace storage for local MVP usage."""

    def __init__(self, base_dir: Union[str, Path] = ".surgeon", filename: str = "trace.json") -> None:
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / filename
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def reset(self) -> None:
        with self._lock:
            self._ensure_file()
            self.path.write_text("[]\n", encoding="utf-8")

    def append(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_file()
            events = self.load()
            events.append(event)
            self.path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def load(self) -> list[dict[str, Any]]:
        self._ensure_file()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        return json.loads(raw)
