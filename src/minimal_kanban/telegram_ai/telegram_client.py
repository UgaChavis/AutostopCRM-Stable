from __future__ import annotations

from typing import Any

import httpx

from .config import TelegramAIConfig


class TelegramApiError(RuntimeError):
    pass


class TelegramBotClient:
    def __init__(self, config: TelegramAIConfig) -> None:
        if not config.bot_token:
            raise TelegramApiError("Telegram bot token is not configured.")
        self._token = config.bot_token
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._file_base_url = f"https://api.telegram.org/file/bot{self._token}"
        self._timeout = config.telegram_request_timeout_seconds

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": int(timeout_seconds),
            "allowed_updates": ["message", "edited_message"],
        }
        if offset is not None:
            payload["offset"] = int(offset)
        response = self._post("getUpdates", payload)
        result = response.get("result")
        return result if isinstance(result, list) else []

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": int(chat_id),
            "text": self._clamp_message(text),
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        return self._post("sendMessage", payload)

    def get_file(self, file_id: str) -> dict[str, Any]:
        payload = self._post("getFile", {"file_id": str(file_id or "")})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramApiError("Telegram getFile returned an unexpected payload.")
        return result

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        file_meta = self.get_file(file_id)
        file_path = str(file_meta.get("file_path") or "").strip()
        if not file_path:
            raise TelegramApiError("Telegram getFile did not return file_path.")
        url = f"{self._file_base_url}/{file_path}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramApiError("Telegram file download failed.") from exc
        return response.content, file_path

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self._base_url}/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramApiError(f"Telegram API request failed: {method}") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            description = ""
            if isinstance(data, dict):
                description = str(data.get("description") or "")
            raise TelegramApiError(f"Telegram API rejected request: {method}: {description}")
        return data

    def _clamp_message(self, text: str) -> str:
        message = str(text or "").strip() or "Не выполнил: пустой ответ."
        if len(message) <= 3900:
            return message
        return message[:3800].rstrip() + "\n\n...ответ сокращён."
