from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TelegramAIStateStore:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {}
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def update(self, **updates: Any) -> dict[str, Any]:
        state = self.read()
        state.update(updates)
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return state
