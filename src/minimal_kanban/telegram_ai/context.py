from __future__ import annotations

from typing import Any

from ..mcp.client import BoardApiClient


class CRMContextBuilder:
    def __init__(self, board_api: BoardApiClient) -> None:
        self._board_api = board_api

    def build(self, *, command_text: str) -> dict[str, Any]:
        snapshot = self._safe_call(
            "get_board_snapshot",
            lambda: self._board_api.get_board_snapshot(
                compact=True,
                archive_limit=5,
                include_archive=False,
            ),
        )
        review = self._safe_call("review_board", self._board_api.review_board)
        search = {}
        query = _search_query_hint(command_text)
        if query:
            search = self._safe_call(
                "search_cards",
                lambda: self._board_api.search_cards(query=query, limit=8),
            )
        return {
            "board_snapshot": _api_data(snapshot),
            "board_review": _api_data(review),
            "search_hint": query,
            "search_results": _api_data(search) if search else {},
        }

    def summary(self, context: dict[str, Any]) -> dict[str, Any]:
        snapshot = context.get("board_snapshot") if isinstance(context, dict) else {}
        data = snapshot if isinstance(snapshot, dict) else {}
        cards = data.get("cards") if isinstance(data.get("cards"), list) else []
        columns = data.get("columns") if isinstance(data.get("columns"), list) else []
        return {
            "cards_visible": len(cards),
            "columns_visible": len(columns),
            "search_hint": context.get("search_hint") if isinstance(context, dict) else "",
        }

    def _safe_call(self, name: str, callback) -> dict[str, Any]:
        try:
            payload = callback()
        except Exception as exc:  # pragma: no cover - transport fallback
            return {"ok": False, "error": {"code": f"{name}_failed", "message": str(exc)}}
        return (
            payload
            if isinstance(payload, dict)
            else {"ok": False, "error": {"code": "bad_payload"}}
        )


def _api_data(payload: dict[str, Any]) -> Any:
    if not isinstance(payload, dict):
        return {}
    if payload.get("ok") is False:
        return {"error": payload.get("error") or {}}
    return payload.get("data") if "data" in payload else payload


def _search_query_hint(command_text: str) -> str:
    text = str(command_text or "").strip()
    if not text:
        return ""
    tokens = [
        token.strip(".,:;!?()[]{}\"'").strip()
        for token in text.split()
        if len(token.strip(".,:;!?()[]{}\"'")) >= 3
    ]
    stop_words = {
        "создай",
        "перенеси",
        "найди",
        "покажи",
        "добавь",
        "карточку",
        "карточки",
        "заказ",
        "наряд",
        "сегодня",
        "завтра",
    }
    candidates = [token for token in tokens if token.lower() not in stop_words]
    return " ".join(candidates[:5])[:120]
