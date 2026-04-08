from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from ..mcp.client import BoardApiClient, BoardApiTransportError, discover_board_api
from ..models import utc_now_iso
from .config import (
    get_agent_board_api_url,
    get_agent_enabled,
    get_agent_max_steps,
    get_agent_max_tool_result_chars,
    get_agent_name,
    get_agent_openai_model,
    get_agent_poll_interval_seconds,
)
from .instructions import build_default_system_prompt
from .openai_client import AgentModelError, OpenAIJsonAgentClient
from .storage import AgentStorage
from .tools import AgentToolExecutor


DEFAULT_SYSTEM_PROMPT = build_default_system_prompt()


class AgentRunner:
    def __init__(
        self,
        *,
        storage: AgentStorage,
        board_api: BoardApiClient,
        model_client: OpenAIJsonAgentClient,
        logger: logging.Logger,
        actor_name: str | None = None,
        max_steps: int | None = None,
        max_tool_result_chars: int | None = None,
    ) -> None:
        self._storage = storage
        self._board_api = board_api
        self._model_client = model_client
        self._logger = logger
        self._actor_name = actor_name or get_agent_name()
        self._max_steps = max_steps or get_agent_max_steps()
        self._max_tool_result_chars = max_tool_result_chars or get_agent_max_tool_result_chars()
        self._tools = AgentToolExecutor(board_api, actor_name=self._actor_name)

    def run_once(self) -> bool:
        task = self._storage.claim_next_task()
        if task is None:
            self._storage.heartbeat(task_id=None, run_id=None)
            return False
        run_id = f"agrun_{uuid.uuid4().hex[:12]}"
        self._storage.update_status(
            running=True,
            current_task_id=task["id"],
            current_run_id=run_id,
            last_heartbeat=utc_now_iso(),
            last_run_started_at=utc_now_iso(),
            last_error="",
        )
        tool_calls = 0
        started_at = utc_now_iso()
        try:
            summary, result, tool_calls = self._execute_task(task, run_id=run_id)
            completed = self._storage.complete_task(
                task_id=task["id"],
                run_id=run_id,
                summary=summary,
                result=result,
                tool_calls=tool_calls,
            )
            self._storage.append_run(
                {
                    "id": run_id,
                    "task_id": task["id"],
                    "status": "completed",
                    "started_at": started_at,
                    "finished_at": completed["finished_at"],
                    "source": task["source"],
                    "mode": task["mode"],
                    "task_text": task["task_text"],
                    "summary": summary,
                    "result": result,
                    "tool_calls": tool_calls,
                    "model": self._model_client.model,
                }
            )
            self._storage.update_status(
                running=False,
                current_task_id=None,
                current_run_id=None,
                last_heartbeat=utc_now_iso(),
                last_run_finished_at=completed["finished_at"],
                last_error="",
            )
            self._logger.info("agent_task_completed task_id=%s run_id=%s tool_calls=%s", task["id"], run_id, tool_calls)
            return True
        except Exception as exc:
            failed = self._storage.fail_task(
                task_id=task["id"],
                run_id=run_id,
                error=str(exc),
                tool_calls=tool_calls,
            )
            self._storage.append_run(
                {
                    "id": run_id,
                    "task_id": task["id"],
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": failed["finished_at"],
                    "source": task["source"],
                    "mode": task["mode"],
                    "task_text": task["task_text"],
                    "summary": "",
                    "result": "",
                    "error": str(exc),
                    "tool_calls": tool_calls,
                    "model": self._model_client.model,
                }
            )
            self._storage.update_status(
                running=False,
                current_task_id=None,
                current_run_id=None,
                last_heartbeat=utc_now_iso(),
                last_run_finished_at=failed["finished_at"],
                last_error=str(exc),
            )
            self._logger.exception("agent_task_failed task_id=%s run_id=%s error=%s", task["id"], run_id, exc)
            return True

    def _execute_task(self, task: dict[str, Any], *, run_id: str) -> tuple[str, str, int]:
        prompt_override = self._storage.read_prompt_text().strip()
        memory_text = self._storage.read_memory_text().strip()
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if prompt_override and prompt_override != DEFAULT_SYSTEM_PROMPT:
            system_prompt = f"{system_prompt}\n\nLocal instructions:\n{prompt_override}"
        if memory_text:
            system_prompt = f"{system_prompt}\n\nPersistent memory:\n{memory_text}"
        system_prompt = f"{system_prompt}\n\nAvailable tools:\n{self._tools.describe_for_prompt()}"
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        messages: list[dict[str, str]] = [
            {
                "role": "user",
                "content": self._build_user_task_message(task, metadata),
            }
        ]
        tool_calls = 0
        for step in range(1, self._max_steps + 1):
            self._storage.heartbeat(task_id=task["id"], run_id=run_id)
            decision = self._model_client.next_step(system_prompt=system_prompt, messages=messages)
            decision_type = str(decision.get("type", "") or "").strip().lower()
            if decision_type == "final":
                summary = str(decision.get("summary", "") or "").strip() or "Task completed."
                result = str(decision.get("result", "") or "").strip() or summary
                return summary, result, tool_calls
            if decision_type != "tool":
                raise AgentModelError("Agent model returned neither a tool call nor a final answer.")
            tool_name = str(decision.get("tool", "") or "").strip()
            args = decision.get("args")
            if not isinstance(args, dict):
                args = {}
            reason = str(decision.get("reason", "") or "").strip()
            tool_calls += 1
            started_at = utc_now_iso()
            result_payload = self._tools.execute(tool_name, args)
            finished_at = utc_now_iso()
            self._storage.append_action(
                {
                    "id": f"agact_{uuid.uuid4().hex[:12]}",
                    "task_id": task["id"],
                    "run_id": run_id,
                    "step": step,
                    "tool": tool_name,
                    "args": args,
                    "reason": reason,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "result_preview": self._preview_payload(result_payload),
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"type": "tool", "tool": tool_name, "args": args, "reason": reason},
                        ensure_ascii=False,
                    ),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": f"TOOL RESULT {tool_name}:\n{self._preview_payload(result_payload)}",
                }
            )
        raise AgentModelError(f"Agent exceeded max steps ({self._max_steps}) without returning a final answer.")

    def _preview_payload(self, payload: dict[str, Any]) -> str:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(text) <= self._max_tool_result_chars:
            return text
        return f"{text[: self._max_tool_result_chars]}... [truncated]"

    def _build_user_task_message(self, task: dict[str, Any], metadata: dict[str, Any]) -> str:
        lines = [
            f"Task id: {task['id']}",
            f"Mode: {task.get('mode', 'manual')}",
            f"Source: {task.get('source', 'manual')}",
        ]
        requested_by = str(metadata.get("requested_by", "") or "").strip()
        if requested_by:
            lines.append(f"Requested by: {requested_by}")
        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        if context:
            lines.append("Context metadata:")
            lines.append(json.dumps(context, ensure_ascii=False, indent=2))
            if str(context.get("kind", "")).strip().lower() == "card":
                lines.append("This task was opened from a card. Work with this card first and inside this card first.")
        lines.append("Task:")
        lines.append(str(task.get("task_text", "") or "").strip())
        return "\n".join(lines)


def build_board_api_client(*, logger: logging.Logger) -> BoardApiClient:
    board_api_url = get_agent_board_api_url() or discover_board_api(timeout_seconds=1.0)
    if not board_api_url:
        raise RuntimeError("Unable to discover a reachable local board API for the server agent.")
    try:
        client = BoardApiClient(board_api_url, logger=logger, default_source="agent")
        health = client.health()
    except BoardApiTransportError as exc:
        raise RuntimeError(f"Board API is not reachable for the server agent: {exc}") from exc
    if not health.get("ok"):
        raise RuntimeError("Board API health check failed for the server agent.")
    return client


def run_agent_loop(*, logger: logging.Logger) -> int:
    if not get_agent_enabled():
        logger.info("agent_runtime_disabled")
        return 0
    storage = AgentStorage()
    idle_sleep = get_agent_poll_interval_seconds()
    if not storage.read_prompt_text().strip():
        storage.write_prompt_text(DEFAULT_SYSTEM_PROMPT)
    if not storage.read_memory_text().strip():
        storage.write_memory_text(
            "CRM URL: https://crm.autostopcrm.ru\n"
            "MCP URL: https://crm.autostopcrm.ru/mcp\n"
            "Default admin: admin/admin\n"
            "Use cashbox names exactly as they exist.\n"
            "If payment goes to cashbox 'Безналичный', the repair order adds 15% taxes and fees from that payment amount.\n"
            "Cashboxes 'Наличный' and 'Карта Мария' do not add taxes and fees.\n"
        )
    board_api = None
    while board_api is None:
        try:
            board_api = build_board_api_client(logger=logger)
        except Exception as exc:
            storage.update_status(
                running=False,
                current_task_id=None,
                current_run_id=None,
                last_heartbeat=utc_now_iso(),
                last_error=str(exc),
            )
            logger.warning("agent_waiting_for_board_api error=%s", exc)
            time.sleep(idle_sleep)
    model_client = OpenAIJsonAgentClient()
    runner = AgentRunner(storage=storage, board_api=board_api, model_client=model_client, logger=logger)
    logger.info("agent_runtime_started model=%s board_api_url=%s", get_agent_openai_model(), board_api.base_url)
    while True:
        try:
            processed = runner.run_once()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            storage.update_status(
                running=False,
                current_task_id=None,
                current_run_id=None,
                last_heartbeat=utc_now_iso(),
                last_error=str(exc),
            )
            logger.exception("agent_runtime_loop_failed error=%s", exc)
            time.sleep(idle_sleep)
            continue
        time.sleep(idle_sleep if not processed else 0.2)
    return 0
