"""QQ 绑定认证 API 客户端。"""

from __future__ import annotations

from typing import Any

from .base import BaseApiClient


class QqBindingApiClient(BaseApiClient):
    """封装 QQ 绑定状态、申请 Key 和确认绑定接口。"""

    async def get_status(self, user_id: str) -> dict[str, Any]:
        """查询当前 AstrBot 用户的 QQ 绑定状态。"""
        return await self.request(
            "GET", "/api/qq-binding/status", query={"user_id": user_id}
        )

    async def request_key(self, user_id: str, qq: str) -> dict[str, Any]:
        """为指定 QQ 号申请临时绑定 Key。"""
        return await self.request(
            "POST",
            "/api/qq-binding/request",
            json_data={"user_id": user_id, "qq_number": qq},
        )

    async def confirm(self, user_id: str, qq: str, key: str) -> dict[str, Any]:
        """使用临时 Key 确认 QQ 绑定。"""
        return await self.request(
            "POST",
            "/api/qq-binding/confirm",
            json_data={"user_id": user_id, "qq_number": qq, "temp_key": key},
        )
