"""用户认证和 QQ 绑定流程状态管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass(slots=True)
class PendingBinding:
    """记录等待确认的 QQ 绑定申请。"""

    qq: str
    key: str
    created_at: float = field()


class AuthStateManager:
    """维护运行期绑定状态缓存，避免频繁重复请求。"""

    def __init__(self, pending_ttl_seconds: int = 600):
        self._bound_users: dict[str, dict[str, str]] = {}
        self._pending_bindings: dict[str, PendingBinding] = {}
        self._pending_ttl_seconds = max(int(pending_ttl_seconds), 0)

    def set_bound(self, user_id: str, status: dict[str, str]) -> None:
        """缓存已绑定用户信息。"""
        self._bound_users[user_id] = status
        self._pending_bindings.pop(user_id, None)

    def clear_bound(self, user_id: str) -> None:
        """清理用户绑定缓存。"""
        self._bound_users.pop(user_id, None)

    def is_bound(self, user_id: str) -> bool:
        """判断用户是否已经完成 QQ 绑定。"""
        return user_id in self._bound_users

    def get_bound(self, user_id: str) -> dict[str, str] | None:
        """读取用户绑定缓存。"""
        return self._bound_users.get(user_id)

    def set_pending(self, user_id: str, qq: str, key: str) -> None:
        """记录待确认的绑定 Key。"""
        self._pending_bindings[user_id] = PendingBinding(qq=qq, key=key, created_at=time())

    def get_pending(self, user_id: str) -> PendingBinding | None:
        """读取待确认的绑定申请。"""
        pending = self._pending_bindings.get(user_id)
        if pending and self._is_pending_expired(pending):
            self.clear_pending(user_id)
            return None
        return pending

    def clear_pending(self, user_id: str) -> None:
        """清理待确认绑定申请。"""
        self._pending_bindings.pop(user_id, None)

    def _is_pending_expired(self, pending: PendingBinding) -> bool:
        """判断待确认绑定是否已过期。"""
        if self._pending_ttl_seconds == 0:
            return False
        return time() - pending.created_at > self._pending_ttl_seconds
