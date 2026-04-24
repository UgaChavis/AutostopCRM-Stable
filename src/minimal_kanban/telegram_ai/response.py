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
        detail = _tool_result_detail(item)
        if detail:
            lines.append(detail)
    response = str(model_decision.get("telegram_response") or "").strip()
    if response:
        lines.append(response)
    return "\n".join(lines)


def _tool_result_detail(item: dict[str, Any]) -> str:
    tool_name = str(item.get("tool") or "")
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if tool_name == "analyze_card_image_attachment":
        facts = data.get("image_facts") if isinstance(data.get("image_facts"), dict) else {}
        if not facts:
            return ""
        compact = []
        for key in ("vin", "license_plate", "make", "model", "mileage", "confidence", "notes"):
            value = facts.get(key)
            if value:
                compact.append(f"{key}: {value}")
        return "  Фото: " + "; ".join(compact[:7]) if compact else ""
    if tool_name == "attach_telegram_photo_to_card":
        attachment = data.get("attachment") if isinstance(data.get("attachment"), dict) else {}
        file_name = str(attachment.get("file_name") or "").strip()
        return f"  Вложение: {file_name}" if file_name else ""
    return ""


def build_recent_actions_response(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "AI пока не записал действий в журнал."
    lines = ["Последние действия AI:"]
    for row in rows[:10]:
        status = row.get("final_status") or "-"
        command = row.get("normalized_command") or row.get("raw_text") or "-"
        lines.append(f"- {row.get('created_at') or '-'} | {status} | {str(command)[:90]}")
    return "\n".join(lines)
