from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..mcp.client import BoardApiClient


class CRMToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class CRMToolDefinition:
    name: str
    description: str
    args_schema: dict[str, Any]
    write: bool = False
    min_role: str = "owner"

    def for_model(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema,
            "write": self.write,
            "min_role": self.min_role,
        }


class CRMToolRegistry:
    def __init__(
        self,
        board_api: BoardApiClient,
        *,
        actor_name: str = "TELEGRAM_AI",
        max_batch_cards: int = 20,
    ) -> None:
        self._board_api = board_api
        self._actor_name = actor_name
        self._max_batch_cards = max(1, int(max_batch_cards))
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_board_snapshot": self._get_board_snapshot,
            "search_cards": self._search_cards,
            "get_card_context": self._get_card_context,
            "create_card": self._create_card,
            "update_card": self._update_card,
            "move_card": self._move_card,
            "archive_card": self._archive_card,
            "set_card_deadline": self._set_card_deadline,
            "set_card_indicator": self._set_card_indicator,
            "list_overdue_cards": self._list_overdue_cards,
            "get_repair_order": self._get_repair_order,
            "update_repair_order": self._update_repair_order,
            "replace_repair_order_works": self._replace_repair_order_works,
            "replace_repair_order_materials": self._replace_repair_order_materials,
            "set_repair_order_status": self._set_repair_order_status,
        }

    @property
    def definitions(self) -> list[CRMToolDefinition]:
        return [
            CRMToolDefinition(
                "get_board_snapshot", "Read compact board snapshot.", {"compact": "optional bool"}
            ),
            CRMToolDefinition(
                "search_cards",
                "Search cards by query.",
                {"query": "required string", "limit": "optional int"},
            ),
            CRMToolDefinition(
                "get_card_context", "Read one focused card context.", {"card_id": "required string"}
            ),
            CRMToolDefinition(
                "list_overdue_cards", "List overdue cards.", {"include_archived": "optional bool"}
            ),
            CRMToolDefinition(
                "get_repair_order", "Read repair order by card id.", {"card_id": "required string"}
            ),
            CRMToolDefinition(
                "create_card",
                "Create CRM card.",
                {
                    "title": "required string",
                    "vehicle": "optional string",
                    "description": "optional string",
                    "column": "optional string",
                    "tags": "optional array",
                    "deadline": "optional object",
                    "vehicle_profile": "optional object",
                },
                write=True,
            ),
            CRMToolDefinition(
                "update_card",
                "Update CRM card fields.",
                {
                    "card_id": "required string",
                    "title": "optional string",
                    "vehicle": "optional string",
                    "description": "optional string",
                    "tags": "optional array",
                    "deadline": "optional object",
                    "vehicle_profile": "optional object",
                },
                write=True,
            ),
            CRMToolDefinition(
                "move_card",
                "Move CRM card to a column.",
                {
                    "card_id": "required string",
                    "column": "required string",
                    "before_card_id": "optional string",
                },
                write=True,
            ),
            CRMToolDefinition(
                "archive_card",
                "Archive CRM card; never hard delete.",
                {"card_id": "required string"},
                write=True,
            ),
            CRMToolDefinition(
                "set_card_deadline",
                "Set card deadline.",
                {"card_id": "required string", "deadline": "required object"},
                write=True,
            ),
            CRMToolDefinition(
                "set_card_indicator",
                "Set card indicator.",
                {"card_id": "required string", "indicator": "required string"},
                write=True,
            ),
            CRMToolDefinition(
                "update_repair_order",
                "Update full repair order object.",
                {"card_id": "required string", "repair_order": "required object"},
                write=True,
            ),
            CRMToolDefinition(
                "replace_repair_order_works",
                "Replace repair order works rows.",
                {"card_id": "required string", "rows": "required array"},
                write=True,
            ),
            CRMToolDefinition(
                "replace_repair_order_materials",
                "Replace repair order material rows.",
                {"card_id": "required string", "rows": "required array"},
                write=True,
            ),
            CRMToolDefinition(
                "set_repair_order_status",
                "Set repair order status.",
                {"card_id": "required string", "status": "required string"},
                write=True,
            ),
        ]

    def catalog_for_model(self) -> list[dict[str, Any]]:
        return [definition.for_model() for definition in self.definitions]

    def execute(self, action: dict[str, Any], *, role: str) -> dict[str, Any]:
        tool_name = str(action.get("tool") or "").strip()
        arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        definition = self._definition(tool_name)
        if definition is None or tool_name not in self._handlers:
            raise CRMToolError(f"Unknown CRM tool: {tool_name}")
        if definition.write and role != "owner":
            raise CRMToolError(f"Role {role} cannot execute write tool {tool_name}.")
        self._validate_batch(tool_name, arguments)
        before = self._before_snapshot(tool_name, arguments) if definition.write else {}
        result = self._handlers[tool_name](dict(arguments))
        if not _api_ok(result):
            raise CRMToolError(_api_error_message(result, default=f"CRM tool failed: {tool_name}"))
        verify = self.verify(tool_name, arguments, result) if definition.write else {"passed": True}
        if definition.write and not verify.get("passed"):
            raise CRMToolError(
                f"CRM write verification failed for {tool_name}: {verify.get('message') or ''}"
            )
        return {
            "tool": tool_name,
            "arguments": arguments,
            "before": before,
            "result": result,
            "verify": verify,
        }

    def rollback_tool_result(self, tool_result: dict[str, Any], *, role: str) -> dict[str, Any]:
        if role != "owner":
            raise CRMToolError(f"Role {role} cannot rollback CRM writes.")
        tool_name = str(tool_result.get("tool") or "").strip()
        before = tool_result.get("before") if isinstance(tool_result.get("before"), dict) else {}
        result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
        if tool_name == "create_card":
            card_id = str(_api_data(result).get("card", {}).get("id") or "")
            if not card_id:
                raise CRMToolError("Cannot rollback create_card without created card id.")
            rollback_result = self._board_api.archive_card(
                card_id=card_id, actor_name=self._actor_name
            )
            return {"tool": "rollback_create_card", "result": rollback_result}
        if tool_name == "move_card":
            card = _api_data(before).get("card", {})
            card_id = str(card.get("id") or "")
            column = str(card.get("column") or "")
            if not card_id or not column:
                raise CRMToolError("Cannot rollback move_card without before column.")
            rollback_result = self._board_api.move_card(
                card_id=card_id,
                column=column,
                actor_name=self._actor_name,
            )
            return {"tool": "rollback_move_card", "result": rollback_result}
        if tool_name == "archive_card":
            card = _api_data(before).get("card", {})
            card_id = str(card.get("id") or "")
            column = str(card.get("column") or "")
            if not card_id:
                raise CRMToolError("Cannot rollback archive_card without before card id.")
            rollback_result = self._board_api.restore_card(
                card_id=card_id,
                column=column or None,
                actor_name=self._actor_name,
            )
            return {"tool": "rollback_archive_card", "result": rollback_result}
        if tool_name in {"update_card", "set_card_deadline", "set_card_indicator"}:
            card = _api_data(before).get("card", {})
            card_id = str(card.get("id") or "")
            if not card_id:
                raise CRMToolError("Cannot rollback update_card without before card.")
            rollback_result = self._board_api.update_card(
                card_id=card_id,
                title=str(card.get("title") or ""),
                vehicle=str(card.get("vehicle") or ""),
                description=str(card.get("description") or ""),
                tags=card.get("tags") if isinstance(card.get("tags"), list) else None,
                vehicle_profile=card.get("vehicle_profile")
                if isinstance(card.get("vehicle_profile"), dict)
                else None,
                actor_name=self._actor_name,
            )
            return {"tool": "rollback_update_card", "result": rollback_result}
        if tool_name in {
            "update_repair_order",
            "replace_repair_order_works",
            "replace_repair_order_materials",
            "set_repair_order_status",
        }:
            data = _api_data(before)
            repair_order = (
                data.get("repair_order") if isinstance(data.get("repair_order"), dict) else {}
            )
            card = data.get("card") if isinstance(data.get("card"), dict) else {}
            card_id = str(card.get("id") or repair_order.get("card_id") or "")
            if not card_id or not repair_order:
                raise CRMToolError("Cannot rollback repair order without before snapshot.")
            rollback_result = self._board_api.update_repair_order(
                card_id=card_id,
                repair_order=repair_order,
                actor_name=self._actor_name,
            )
            return {"tool": "rollback_repair_order", "result": rollback_result}
        raise CRMToolError(f"Rollback is not supported for {tool_name}.")

    def verify(
        self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return self._verify(tool_name, arguments, result)
        except Exception as exc:  # pragma: no cover - defensive verifier path
            return {"passed": False, "message": str(exc)}

    def _verify(
        self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        if tool_name == "create_card":
            card = _api_data(result).get("card", {})
            card_id = str(card.get("id") or "")
            if not card_id:
                return {"passed": False, "message": "created card id is missing"}
            return self._verify_card_exists(card_id)
        if tool_name in {"update_card", "set_card_deadline", "set_card_indicator"}:
            return self._verify_card_exists(str(arguments.get("card_id") or ""))
        if tool_name == "move_card":
            card_payload = self._read_card(str(arguments.get("card_id") or ""))
            card = _api_data(card_payload).get("card", {})
            expected_column = str(arguments.get("column") or "")
            return {
                "passed": bool(card) and str(card.get("column") or "") == expected_column,
                "message": "column matched"
                if str(card.get("column") or "") == expected_column
                else "column mismatch",
            }
        if tool_name == "archive_card":
            card_payload = self._read_card(str(arguments.get("card_id") or ""))
            card = _api_data(card_payload).get("card", {})
            return {"passed": bool(card.get("archived")), "message": "archived flag checked"}
        if tool_name in {
            "update_repair_order",
            "replace_repair_order_works",
            "replace_repair_order_materials",
            "set_repair_order_status",
        }:
            payload = self._board_api.get_repair_order(str(arguments.get("card_id") or ""))
            return {"passed": _api_ok(payload), "message": "repair order read-back checked"}
        return {"passed": True, "message": "no specific verifier"}

    def _verify_card_exists(self, card_id: str) -> dict[str, Any]:
        payload = self._read_card(card_id)
        card = _api_data(payload).get("card", {})
        return {"passed": bool(card.get("id")), "message": "card read-back checked"}

    def _before_snapshot(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "create_card":
            return {}
        card_id = str(arguments.get("card_id") or "")
        if tool_name in {
            "update_repair_order",
            "replace_repair_order_works",
            "replace_repair_order_materials",
            "set_repair_order_status",
        }:
            return self._board_api.get_repair_order(card_id) if card_id else {}
        return self._read_card(card_id) if card_id else {}

    def _read_card(self, card_id: str) -> dict[str, Any]:
        if not card_id:
            return {"ok": False, "error": {"message": "card_id is missing"}}
        return self._board_api.get_card(card_id)

    def _definition(self, tool_name: str) -> CRMToolDefinition | None:
        for definition in self.definitions:
            if definition.name == tool_name:
                return definition
        return None

    def _validate_batch(self, tool_name: str, arguments: dict[str, Any]) -> None:
        if tool_name != "move_card":
            return
        card_ids = arguments.get("card_ids")
        if isinstance(card_ids, list) and len(card_ids) > self._max_batch_cards:
            raise CRMToolError(
                f"Batch card limit exceeded: {len(card_ids)} > {self._max_batch_cards}"
            )

    def _get_board_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.get_board_snapshot(compact=bool(arguments.get("compact", True)))

    def _search_cards(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.search_cards(
            query=str(arguments.get("query") or ""),
            limit=int(arguments.get("limit") or 10),
            include_archived=bool(arguments.get("include_archived", False)),
        )

    def _get_card_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.get_card_context(str(arguments.get("card_id") or ""))

    def _create_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.create_card(
            title=str(arguments.get("title") or "").strip(),
            vehicle=str(arguments.get("vehicle") or ""),
            description=str(arguments.get("description") or ""),
            column=str(arguments.get("column") or "") or None,
            tags=arguments.get("tags") if isinstance(arguments.get("tags"), list) else None,
            deadline=arguments.get("deadline")
            if isinstance(arguments.get("deadline"), dict)
            else None,
            vehicle_profile=arguments.get("vehicle_profile")
            if isinstance(arguments.get("vehicle_profile"), dict)
            else None,
            actor_name=self._actor_name,
        )

    def _update_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.update_card(
            card_id=str(arguments.get("card_id") or ""),
            title=_optional_text(arguments, "title"),
            vehicle=_optional_text(arguments, "vehicle"),
            description=_optional_text(arguments, "description"),
            tags=arguments.get("tags") if isinstance(arguments.get("tags"), list) else None,
            deadline=arguments.get("deadline")
            if isinstance(arguments.get("deadline"), dict)
            else None,
            vehicle_profile=arguments.get("vehicle_profile")
            if isinstance(arguments.get("vehicle_profile"), dict)
            else None,
            actor_name=self._actor_name,
        )

    def _move_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.move_card(
            card_id=str(arguments.get("card_id") or ""),
            column=str(arguments.get("column") or ""),
            before_card_id=_optional_text(arguments, "before_card_id"),
            actor_name=self._actor_name,
        )

    def _archive_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.archive_card(
            card_id=str(arguments.get("card_id") or ""), actor_name=self._actor_name
        )

    def _set_card_deadline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.set_card_deadline(
            card_id=str(arguments.get("card_id") or ""),
            deadline=arguments.get("deadline")
            if isinstance(arguments.get("deadline"), dict)
            else {},
            actor_name=self._actor_name,
        )

    def _set_card_indicator(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.set_card_indicator(
            card_id=str(arguments.get("card_id") or ""),
            indicator=str(arguments.get("indicator") or ""),
            actor_name=self._actor_name,
        )

    def _list_overdue_cards(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.list_overdue_cards(
            include_archived=bool(arguments.get("include_archived", False))
        )

    def _get_repair_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.get_repair_order(str(arguments.get("card_id") or ""))

    def _update_repair_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.update_repair_order(
            card_id=str(arguments.get("card_id") or ""),
            repair_order=arguments.get("repair_order")
            if isinstance(arguments.get("repair_order"), dict)
            else {},
            actor_name=self._actor_name,
        )

    def _replace_repair_order_works(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.replace_repair_order_works(
            card_id=str(arguments.get("card_id") or ""),
            rows=arguments.get("rows") if isinstance(arguments.get("rows"), list) else [],
            actor_name=self._actor_name,
        )

    def _replace_repair_order_materials(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.replace_repair_order_materials(
            card_id=str(arguments.get("card_id") or ""),
            rows=arguments.get("rows") if isinstance(arguments.get("rows"), list) else [],
            actor_name=self._actor_name,
        )

    def _set_repair_order_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._board_api.set_repair_order_status(
            card_id=str(arguments.get("card_id") or ""),
            status=str(arguments.get("status") or ""),
            actor_name=self._actor_name,
        )


def _api_ok(payload: dict[str, Any]) -> bool:
    return isinstance(payload, dict) and payload.get("ok") is not False


def _api_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _api_error_message(payload: dict[str, Any], *, default: str) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or default)
    return default


def _optional_text(arguments: dict[str, Any], key: str) -> str | None:
    if key not in arguments:
        return None
    value = arguments.get(key)
    if value is None:
        return None
    return str(value)
