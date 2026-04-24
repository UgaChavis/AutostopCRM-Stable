from __future__ import annotations

# ruff: noqa: E402
import json
import logging
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from minimal_kanban.api.server import ApiServer
from minimal_kanban.mcp.client import BoardApiClient
from minimal_kanban.services.card_service import CardService
from minimal_kanban.storage.json_store import JsonStore
from minimal_kanban.telegram_ai.audit import TelegramAIAuditService, redact_secrets
from minimal_kanban.telegram_ai.auth import TelegramAuthService
from minimal_kanban.telegram_ai.config import TelegramAIConfig
from minimal_kanban.telegram_ai.context import CRMContextBuilder
from minimal_kanban.telegram_ai.crm_tools import CRMToolError, CRMToolRegistry
from minimal_kanban.telegram_ai.normalizer import normalize_update
from minimal_kanban.telegram_ai.openai_client import TelegramAIOpenAIClient
from minimal_kanban.telegram_ai.orchestrator import TelegramAIOrchestrator


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_config(
    temp_dir: str, *, owner_ids: frozenset[int] = frozenset({1001})
) -> TelegramAIConfig:
    return TelegramAIConfig(
        enabled=True,
        bot_token="telegram-token",
        owner_ids=owner_ids,
        openai_api_key="openai-key",
        openai_base_url="https://api.openai.com/v1",
        model="gpt-5.4-mini",
        vision_model="gpt-5.4-mini",
        transcription_model="gpt-4o-mini-transcribe",
        reasoning_effort="medium",
        crm_api_base_url="http://127.0.0.1:41731",
        crm_api_bearer_token=None,
        data_dir=Path(temp_dir) / "telegram_ai",
        audit_enabled=True,
        max_batch_cards=20,
        telegram_poll_timeout_seconds=1,
        telegram_request_timeout_seconds=1.0,
        openai_request_timeout_seconds=1.0,
        autopilot_enabled=False,
        autopilot_interval_minutes=30,
        web_search_enabled=False,
    )


class FakeModelClient:
    model = "fake-model"

    def __init__(self) -> None:
        self.decide_calls = 0

    def decide(self, **kwargs):
        self.decide_calls += 1
        return {
            "intent": "no_action",
            "confidence": "high",
            "actions": [],
            "telegram_response": "Ответ модели",
            "requires_human_confirmation": False,
        }

    def transcribe_audio(self, **kwargs) -> str:
        return "Создай карточку голосом"

    def analyze_image(self, **kwargs):
        return {"vin": "WAUZZZ8V0JA000001", "confidence": "medium"}


class TelegramAINormalizerTests(unittest.TestCase):
    def test_normalize_text_update(self) -> None:
        update = {
            "update_id": 10,
            "message": {
                "message_id": 20,
                "date": 123,
                "chat": {"id": 30},
                "from": {"id": 1001, "username": "owner"},
                "text": "Кратко по доске",
            },
        }

        normalized = normalize_update(update)

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized.update_id, 10)
        self.assertEqual(normalized.chat_id, 30)
        self.assertEqual(normalized.user_id, 1001)
        self.assertEqual(normalized.input_type, "text")
        self.assertEqual(normalized.command_text, "Кратко по доске")

    def test_normalize_voice_and_best_photo(self) -> None:
        voice_update = {
            "update_id": 11,
            "message": {
                "message_id": 21,
                "chat": {"id": 31},
                "from": {"id": 1001},
                "voice": {"file_id": "voice-1", "file_unique_id": "v1", "mime_type": "audio/ogg"},
            },
        }
        photo_update = {
            "update_id": 12,
            "message": {
                "message_id": 22,
                "chat": {"id": 32},
                "from": {"id": 1001},
                "caption": "по BMW",
                "photo": [
                    {"file_id": "small", "file_size": 10, "width": 10, "height": 10},
                    {"file_id": "large", "file_size": 100, "width": 100, "height": 100},
                ],
            },
        }

        voice = normalize_update(voice_update)
        photo = normalize_update(photo_update)

        self.assertEqual(voice.input_type, "voice")
        self.assertEqual(voice.attachments[0].file_id, "voice-1")
        self.assertEqual(photo.input_type, "photo")
        self.assertEqual(photo.attachments[0].file_id, "large")
        self.assertEqual(photo.command_text, "по BMW")


class TelegramAIAuthAuditTests(unittest.TestCase):
    def test_owner_authorization_and_denial(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth = TelegramAuthService(build_config(temp_dir, owner_ids=frozenset({42})))
            self.assertEqual(auth.resolve(user_id=42).role, "owner")
            self.assertFalse(auth.resolve(user_id=43).is_authorized)

    def test_audit_redacts_secrets(self) -> None:
        payload = redact_secrets(
            {
                "bot_token": "telegram-secret",
                "nested": {"OPENAI_API_KEY": "openai-secret"},
                "safe": "value",
            }
        )

        self.assertEqual(payload["bot_token"], "***")
        self.assertEqual(payload["nested"]["OPENAI_API_KEY"], "***")
        self.assertEqual(payload["safe"], "value")


class TelegramAIOrchestratorTests(unittest.TestCase):
    def test_unauthorized_user_does_not_call_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(temp_dir, owner_ids=frozenset({1001}))
            audit = TelegramAIAuditService(config.audit_file)
            model = FakeModelClient()
            orchestrator = TelegramAIOrchestrator(
                auth=TelegramAuthService(config),
                model_client=model,
                context_builder=object(),
                tool_registry=object(),
                audit=audit,
            )
            normalized = normalize_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 3},
                        "from": {"id": 999},
                        "text": "Кратко по доске",
                    },
                }
            )

            response = orchestrator.handle(normalized)

            self.assertEqual(response, "Доступ запрещён.")
            self.assertEqual(model.decide_calls, 0)
            rows = config.audit_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["final_status"], "failed")

    def test_status_command_does_not_call_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(temp_dir, owner_ids=frozenset({1001}))
            model = FakeModelClient()
            orchestrator = TelegramAIOrchestrator(
                auth=TelegramAuthService(config),
                model_client=model,
                context_builder=object(),
                tool_registry=object(),
                audit=TelegramAIAuditService(config.audit_file),
            )
            normalized = normalize_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 3},
                        "from": {"id": 1001},
                        "text": "/status",
                    },
                }
            )

            response = orchestrator.handle(normalized)

            self.assertIn("Telegram AI worker активен", response)
            self.assertEqual(model.decide_calls, 0)


class TelegramAITranscriptionTests(unittest.TestCase):
    def test_voice_ogg_is_converted_before_transcription_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(temp_dir)
            client = TelegramAIOpenAIClient(config)
            captured: dict[str, object] = {}

            class FakeResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, object]:
                    return {"text": "Создай карточку"}

            class FakeHttpxClient:
                def __init__(self, *args, **kwargs) -> None:
                    return None

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb) -> None:
                    return None

                def post(self, url, headers=None, data=None, files=None):
                    captured["url"] = url
                    captured["headers"] = headers
                    captured["data"] = data
                    captured["files"] = files
                    return FakeResponse()

            def fake_run(cmd, check, capture_output, text):
                Path(cmd[-1]).write_bytes(b"mp3-bytes")
                return None

            with (
                patch(
                    "minimal_kanban.telegram_ai.openai_client.shutil.which", return_value="ffmpeg"
                ),
                patch(
                    "minimal_kanban.telegram_ai.openai_client.subprocess.run", side_effect=fake_run
                ),
                patch("minimal_kanban.telegram_ai.openai_client.httpx.Client", FakeHttpxClient),
            ):
                text = client.transcribe_audio(
                    audio_bytes=b"ogg-bytes",
                    filename="voice.ogg",
                    mime_type="audio/ogg",
                )

            self.assertEqual(text, "Создай карточку")
            file_name, file_bytes, file_mime = captured["files"]["file"]
            self.assertTrue(str(file_name).endswith(".mp3"))
            self.assertEqual(file_bytes, b"mp3-bytes")
            self.assertEqual(file_mime, "audio/mpeg")
            self.assertEqual(captured["data"]["model"], "gpt-4o-mini-transcribe")


class TelegramAIResponsesPayloadTests(unittest.TestCase):
    def test_decide_payload_omits_temperature_for_responses_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(temp_dir)
            client = TelegramAIOpenAIClient(config)
            captured: dict[str, object] = {}

            def fake_post_with_retry(path: str, payload: dict[str, object]) -> dict[str, object]:
                captured["path"] = path
                captured["payload"] = payload
                return {
                    "output_text": json.dumps(
                        {
                            "intent": "no_action",
                            "confidence": "high",
                            "actions": [],
                            "telegram_response": "ok",
                            "requires_human_confirmation": False,
                        },
                        ensure_ascii=False,
                    )
                }

            with patch.object(
                TelegramAIOpenAIClient, "_post_with_retry", side_effect=fake_post_with_retry
            ):
                result = client.decide(
                    command_text="/status",
                    role="owner",
                    crm_context={},
                    tool_catalog=[],
                )

            self.assertEqual(captured["path"], "/responses")
            payload = captured["payload"]
            self.assertIsInstance(payload, dict)
            assert isinstance(payload, dict)
            self.assertNotIn("temperature", payload)
            self.assertIn("json", json.dumps(payload["input"], ensure_ascii=False).lower())
            self.assertEqual(payload["reasoning"], {"effort": "medium"})
            self.assertEqual(result["intent"], "no_action")


class TelegramAICRMToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        logger = logging.getLogger(f"test.telegram_ai.{self._testMethodName}")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        self.store = JsonStore(state_file=Path(self.temp_dir.name) / "state.json", logger=logger)
        self.service = CardService(self.store, logger)
        self.port = reserve_port()
        self.server = ApiServer(self.service, logger, start_port=self.port, fallback_limit=1)
        self.server.start()
        self.client = BoardApiClient(
            self.server.base_url, logger=logger, default_source="telegram_ai"
        )

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_dir.cleanup()

    def test_registry_create_update_move_with_verification(self) -> None:
        registry = CRMToolRegistry(self.client, actor_name="TEST_TELEGRAM_AI")

        created = registry.execute(
            {
                "tool": "create_card",
                "arguments": {
                    "title": "Telegram AI card",
                    "description": "Создано тестом",
                    "vehicle": "Toyota Camry",
                },
            },
            role="owner",
        )
        card_id = created["result"]["data"]["card"]["id"]
        self.assertTrue(created["verify"]["passed"])

        updated = registry.execute(
            {
                "tool": "update_card",
                "arguments": {"card_id": card_id, "description": "Обновлено Telegram AI"},
            },
            role="owner",
        )
        self.assertTrue(updated["verify"]["passed"])

        moved = registry.execute(
            {"tool": "move_card", "arguments": {"card_id": card_id, "column": "in_progress"}},
            role="owner",
        )
        self.assertTrue(moved["verify"]["passed"])

        fetched = self.client.get_card(card_id)
        self.assertEqual(fetched["data"]["card"]["column"], "in_progress")
        self.assertEqual(fetched["data"]["card"]["description"], "Обновлено Telegram AI")

        rollback = registry.rollback_tool_result(moved, role="owner")
        self.assertEqual(rollback["tool"], "rollback_move_card")
        rolled_back = self.client.get_card(card_id)
        self.assertNotEqual(rolled_back["data"]["card"]["column"], "in_progress")

    def test_registry_rejects_unknown_and_non_owner_write(self) -> None:
        registry = CRMToolRegistry(self.client, actor_name="TEST_TELEGRAM_AI")

        with self.assertRaises(CRMToolError):
            registry.execute({"tool": "unknown_tool", "arguments": {}}, role="owner")
        with self.assertRaises(CRMToolError):
            registry.execute(
                {"tool": "create_card", "arguments": {"title": "Denied"}},
                role="viewer",
            )

    def test_context_builder_reads_board_without_writes(self) -> None:
        self.client.create_card(title="Camry context", description="Проверить ходовую")
        context = CRMContextBuilder(self.client).build(command_text="Покажи Camry")

        self.assertIn("board_snapshot", context)
        self.assertEqual(context["search_hint"], "Camry")
        self.assertIn("search_results", context)


if __name__ == "__main__":
    unittest.main()
