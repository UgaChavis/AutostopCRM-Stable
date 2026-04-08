from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    data = None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _login(base_url: str, username: str, password: str) -> str:
    response = _request_json(
        f"{base_url}/api/login_operator",
        method="POST",
        payload={"username": username, "password": password},
    )
    return response["data"]["session"]["token"]


def _heartbeat_age_seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def _default_api_url() -> str:
    candidate = (
        os.environ.get("MINIMAL_KANBAN_AGENT_BOARD_API_URL")
        or os.environ.get("AUTOSTOP_AGENT_BOARD_API_URL")
        or "http://127.0.0.1:41731"
    )
    return candidate.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-api-url", default=_default_api_url())
    parser.add_argument("--operator-username", default="admin")
    parser.add_argument("--operator-password", default="admin")
    parser.add_argument("--max-heartbeat-age-seconds", type=float, default=30.0)
    args = parser.parse_args()

    try:
        token = _login(args.local_api_url.rstrip("/"), args.operator_username, args.operator_password)
        payload = _request_json(
            f"{args.local_api_url.rstrip('/')}/api/agent_status",
            headers={"X-Operator-Session": token},
        )
        status = payload["data"]["status"]
        agent = payload["data"]["agent"]
        heartbeat_age = _heartbeat_age_seconds(str(status.get("last_heartbeat", "") or ""))
        if not agent.get("enabled"):
            print("status: disabled")
            return 1
        if heartbeat_age is None or heartbeat_age > args.max_heartbeat_age_seconds:
            print(
                "status: stale_heartbeat",
                f"heartbeat_age_seconds={heartbeat_age if heartbeat_age is not None else 'unknown'}",
                f"api_url={args.local_api_url.rstrip('/')}",
            )
            return 1
        print(
            "status: ok",
            f"heartbeat_age_seconds={heartbeat_age:.2f}",
            f"api_url={args.local_api_url.rstrip('/')}",
            f"model={agent.get('model', '')}",
        )
        return 0
    except (KeyError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print("status: error", f"type={type(exc).__name__}", f"detail={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
