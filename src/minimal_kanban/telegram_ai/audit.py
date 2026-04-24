from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import utc_now_iso
from .models import RunContext

SECRET_KEYS = {"token", "api_key", "authorization", "password", "secret", "bot_token"}


class TelegramAIAuditService:
    def __init__(self, audit_file: Path, *, enabled: bool = True) -> None:
        self._audit_file = audit_file
        self._enabled = enabled
        self._audit_file.parent.mkdir(parents=True, exist_ok=True)

    def write_run(self, context: RunContext) -> None:
        if not self._enabled:
            return
        payload = {
            "run_id": context.run_id,
            "created_at": utc_now_iso(),
            "telegram_user_id": context.normalized_input.user_id,
            "telegram_chat_id": context.normalized_input.chat_id,
            "role": context.role,
            "input_type": context.normalized_input.input_type,
            "raw_text": context.normalized_input.text,
            "transcribed_text": context.transcribed_text,
            "caption": context.normalized_input.caption,
            "attachments": [item.to_audit_dict() for item in context.normalized_input.attachments],
            "normalized_command": _normalized_command(context),
            "context_summary": context.context_summary,
            "model_decision": context.model_decision,
            "planned_actions": context.planned_actions,
            "tool_calls": context.tool_calls,
            "tool_results": context.tool_results,
            "verify_result": context.verify_result,
            "final_status": context.final_status,
            "telegram_response": context.telegram_response,
            "error": context.error,
        }
        try:
            self.append(payload)
        except OSError:
            return

    def append(self, payload: dict[str, Any]) -> None:
        safe_payload = redact_secrets(payload)
        with self._audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_payload, ensure_ascii=False, sort_keys=True) + "\n")

    def recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        if not self._audit_file.exists():
            return []
        try:
            lines = self._audit_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in reversed(lines):
            if len(rows) >= max(1, limit):
                break
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows


def redact_secrets(payload: Any) -> Any:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if any(secret in normalized_key for secret in SECRET_KEYS):
                result[key] = "***"
            else:
                result[key] = redact_secrets(value)
        return result
    if isinstance(payload, list):
        return [redact_secrets(item) for item in payload]
    return payload


def _normalized_command(context: RunContext) -> str:
    if context.transcribed_text:
        return context.transcribed_text
    if context.normalized_input.command_text:
        return context.normalized_input.command_text
    if context.image_facts:
        return json.dumps(context.image_facts, ensure_ascii=False, sort_keys=True)
    return ""
