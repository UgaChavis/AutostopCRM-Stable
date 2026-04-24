from __future__ import annotations

from typing import Any

from .models import NormalizedTelegramInput, TelegramAttachment


def normalize_update(update: dict[str, Any]) -> NormalizedTelegramInput | None:
    if not isinstance(update, dict):
        return None
    message = update.get("message") if isinstance(update.get("message"), dict) else None
    if message is None:
        message = (
            update.get("edited_message") if isinstance(update.get("edited_message"), dict) else None
        )
    if message is None:
        return None
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    user = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat_id = _int(chat.get("id"))
    user_id = _int(user.get("id"))
    message_id = _int(message.get("message_id"))
    if chat_id is None or user_id is None or message_id is None:
        return None
    text = str(message.get("text") or "").strip()
    caption = str(message.get("caption") or "").strip()
    attachments = _extract_attachments(message)
    input_type = _input_type(text=text, attachments=attachments)
    return NormalizedTelegramInput(
        update_id=_int(update.get("update_id")) or 0,
        message_id=message_id,
        chat_id=chat_id,
        user_id=user_id,
        username=str(user.get("username") or ""),
        first_name=str(user.get("first_name") or ""),
        input_type=input_type,
        text=text,
        caption=caption,
        attachments=tuple(attachments),
        raw_date=_int(message.get("date")),
    )


def _extract_attachments(message: dict[str, Any]) -> list[TelegramAttachment]:
    attachments: list[TelegramAttachment] = []
    voice = message.get("voice") if isinstance(message.get("voice"), dict) else None
    if voice:
        attachments.append(
            TelegramAttachment(
                kind="voice",
                file_id=str(voice.get("file_id") or ""),
                file_unique_id=str(voice.get("file_unique_id") or ""),
                mime_type=str(voice.get("mime_type") or "audio/ogg"),
                file_size=_int(voice.get("file_size")),
            )
        )
    photos = message.get("photo") if isinstance(message.get("photo"), list) else []
    best_photo = _best_photo(photos)
    if best_photo:
        attachments.append(
            TelegramAttachment(
                kind="photo",
                file_id=str(best_photo.get("file_id") or ""),
                file_unique_id=str(best_photo.get("file_unique_id") or ""),
                mime_type="image/jpeg",
                file_size=_int(best_photo.get("file_size")),
                width=_int(best_photo.get("width")),
                height=_int(best_photo.get("height")),
            )
        )
    document = message.get("document") if isinstance(message.get("document"), dict) else None
    if document:
        mime_type = str(document.get("mime_type") or "")
        kind = "photo" if mime_type.startswith("image/") else "document"
        attachments.append(
            TelegramAttachment(
                kind=kind,
                file_id=str(document.get("file_id") or ""),
                file_unique_id=str(document.get("file_unique_id") or ""),
                mime_type=mime_type,
                file_name=str(document.get("file_name") or ""),
                file_size=_int(document.get("file_size")),
            )
        )
    return [item for item in attachments if item.file_id]


def _best_photo(photos: list[Any]) -> dict[str, Any] | None:
    candidates = [item for item in photos if isinstance(item, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item.get("file_size") or 0))


def _input_type(*, text: str, attachments: list[TelegramAttachment]) -> str:
    if any(item.kind == "voice" for item in attachments):
        return "voice"
    if any(item.kind == "photo" for item in attachments):
        return "photo"
    if attachments:
        return "document"
    return "text" if text else "unknown"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
