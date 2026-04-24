from __future__ import annotations

from typing import Any


def build_execution_response(
    *,
    model_decision: dict[str, Any],
    tool_results: list[dict[str, Any]],
    status: str,
    error: str = "",
) -> str:
    if status == "failed":
        return f"Не выполнил.\nПричина: {error or 'ошибка выполнения'}"
    if not tool_results:
        response = str(model_decision.get("telegram_response") or "").strip()
        return response or "Принял. Действий по CRM не требуется."
    lines = ["Сделано."]
    for item in tool_results[:8]:
        tool_name = str(item.get("tool") or "")
        verify = item.get("verify") if isinstance(item.get("verify"), dict) else {}
        mark = "проверено" if verify.get("passed") else "без проверки"
        lines.append(f"- {tool_name}: {mark}")
    response = str(model_decision.get("telegram_response") or "").strip()
    if response:
        lines.append(response)
    return "\n".join(lines)


def build_recent_actions_response(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "AI пока не записал действий в журнал."
    lines = ["Последние действия AI:"]
    for row in rows[:10]:
        status = row.get("final_status") or "-"
        command = row.get("normalized_command") or row.get("raw_text") or "-"
        lines.append(f"- {row.get('created_at') or '-'} | {status} | {str(command)[:90]}")
    return "\n".join(lines)
