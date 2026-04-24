from __future__ import annotations

from dataclasses import dataclass

from .config import TelegramAIConfig

ROLE_OWNER = "owner"
ROLE_UNAUTHORIZED = "unauthorized"


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    username: str = ""
    role: str = ROLE_UNAUTHORIZED

    @property
    def is_authorized(self) -> bool:
        return self.role != ROLE_UNAUTHORIZED


class TelegramAuthService:
    def __init__(self, config: TelegramAIConfig) -> None:
        self._config = config

    def resolve(self, *, user_id: int, username: str = "") -> TelegramIdentity:
        role = ROLE_OWNER if int(user_id) in self._config.owner_ids else ROLE_UNAUTHORIZED
        return TelegramIdentity(user_id=int(user_id), username=str(username or ""), role=role)
