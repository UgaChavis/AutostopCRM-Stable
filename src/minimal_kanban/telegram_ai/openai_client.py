from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from .config import TelegramAIConfig


class TelegramAIModelError(RuntimeError):
    pass


class TelegramAIOpenAIClient:
    def __init__(self, config: TelegramAIConfig) -> None:
        if not config.openai_api_key:
            raise TelegramAIModelError("OPENAI_API_KEY is not configured.")
        self._api_key = config.openai_api_key
        self._base_url = config.openai_base_url.rstrip("/")
        self._model = config.model
        self._vision_model = config.vision_model
        self._transcription_model = config.transcription_model
        self._reasoning_effort = config.reasoning_effort
        self._timeout_seconds = config.openai_request_timeout_seconds
        self._web_search_enabled = config.web_search_enabled

    @property
    def model(self) -> str:
        return self._model

    def decide(
        self,
        *,
        command_text: str,
        role: str,
        crm_context: dict[str, Any],
        tool_catalog: list[dict[str, Any]],
        image_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        instructions = _decision_instructions(role=role, tool_catalog=tool_catalog)
        user_payload = {
            "command_text": command_text,
            "role": role,
            "crm_context": crm_context,
            "image_facts": image_facts or {},
        }
        return self._responses_json(
            model=self._model,
            instructions=instructions,
            input_messages=[
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
                }
            ],
        )

    def analyze_image(
        self, *, image_bytes: bytes, mime_type: str, caption: str = ""
    ) -> dict[str, Any]:
        data_url = f"data:{mime_type or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        instructions = """
You extract operational facts from auto-service photos for AutoStop CRM.
Return only JSON with keys:
vin, license_plate, make, model, mileage, client_name, phone, symptoms, requested_works,
parts, dates, visible_codes, confidence, notes.
Use empty strings or empty arrays when a fact is not visible. Do not invent facts.
""".strip()
        return self._responses_json(
            model=self._vision_model,
            instructions=instructions,
            input_messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Caption: {caption or '-'}\nExtract CRM facts from this image.",
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )

    def transcribe_audio(self, *, audio_bytes: bytes, filename: str, mime_type: str = "") -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {
            "file": (
                filename or "telegram-voice.ogg",
                audio_bytes,
                mime_type or "audio/ogg",
            )
        }
        data = {"model": self._transcription_model, "response_format": "json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    f"{self._base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramAIModelError("OpenAI transcription request failed.") from exc
        text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        if not text:
            raise TelegramAIModelError("OpenAI transcription returned empty text.")
        return text

    def _responses_json(
        self,
        *,
        model: str,
        instructions: str,
        input_messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_messages,
            "text": {"format": {"type": "json_object"}},
            "temperature": 0.2,
            "reasoning": {"effort": self._reasoning_effort},
            "store": False,
        }
        if self._web_search_enabled:
            payload["tools"] = [
                {
                    "type": "web_search_preview",
                    "search_context_size": "medium",
                }
            ]
        response_payload = self._post_with_retry("/responses", payload)
        output_text = _extract_output_text(response_payload)
        return _parse_json(output_text)

    def _post_with_retry(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.post(f"{self._base_url}{path}", headers=headers, json=payload)
                response.raise_for_status()
                parsed = response.json()
                if not isinstance(parsed, dict):
                    raise TelegramAIModelError("OpenAI returned a non-object payload.")
                return parsed
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {408, 409, 429, 500, 502, 503, 504}:
                    raise TelegramAIModelError(_openai_error_message(exc.response)) from exc
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
            time.sleep(0.6 * attempt)
        raise TelegramAIModelError(f"OpenAI request failed: {last_error}") from last_error


def _decision_instructions(*, role: str, tool_catalog: list[dict[str, Any]]) -> str:
    return (
        "You are AutoStop CRM Telegram AI Board Manager.\n"
        "Language: Russian.\n"
        "Mode: owner/full_control when role is owner. No confirmation is required for owner.\n"
        "You manage only CRM operational data through explicit tools. Never request shell, git, secrets, or raw storage access.\n"
        "If a target is ambiguous and a wrong write could damage CRM data, ask a short clarifying question and return no actions.\n"
        "For normal owner commands, act directly.\n"
        "Return only one JSON object with this shape:\n"
        "{"
        '"intent":"create_card|update_card|move_card|archive_card|repair_order_update|board_report|multi_action|no_action",'
        '"confidence":"high|medium|low",'
        '"actions":[{"tool":"tool_name","arguments":{},"reason":"short reason"}],'
        '"telegram_response":"short Russian response to send after execution or question when no action",'
        '"requires_human_confirmation":false'
        "}\n"
        "Allowed tools with schemas:\n"
        f"{json.dumps(tool_catalog, ensure_ascii=False, sort_keys=True)}\n"
        f"Current role: {role}."
    )


def _extract_output_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("output_text") or "").strip()
    if text:
        return text
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                chunk = content.get("text")
                if chunk:
                    chunks.append(str(chunk))
    return "".join(chunks).strip()


def _parse_json(text: str) -> dict[str, Any]:
    content = str(text or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        if start < 0:
            raise TelegramAIModelError("OpenAI did not return JSON.")
        payload, _ = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(payload, dict):
        raise TelegramAIModelError("OpenAI JSON response is not an object.")
    return payload


def _openai_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"OpenAI HTTP {response.status_code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        code = str(error.get("code") or "").strip()
        if message and code:
            return f"OpenAI HTTP {response.status_code} ({code}): {message}"
        if message:
            return f"OpenAI HTTP {response.status_code}: {message}"
    return f"OpenAI HTTP {response.status_code}"
