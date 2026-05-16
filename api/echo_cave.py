"""回声洞投稿、查询、编辑和删除 API 客户端。"""

from __future__ import annotations

from typing import Any

from .base import BaseApiClient


class EchoCaveApiClient(BaseApiClient):
    """提供回声洞核心资源的高层调用方法。"""

    async def create_echo(
        self, content: str, *, user_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """提交一条新的回声洞内容。"""
        return await self.request(
            "POST",
            "/api/echo-cave/internal",
            json_data={"content": content, "author_id": user_id},
            headers={"x-echo-cave-token": self.config.internal_token}
            if self.config.internal_token
            else None,
            token=token,
        )

    async def get_echo(self, echo_id: str | None = None) -> dict[str, Any]:
        """查询随机或指定编号的回声洞内容。"""
        query = {"id": echo_id} if echo_id else {"mode": "random", "limit": 1}
        return await self.request("GET", "/api/echo-cave", query=query)

    async def update_echo(
        self,
        echo_id: str,
        content: str,
        *,
        user_id: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """更新用户自己的回声洞内容。"""
        return await self.request(
            "PUT",
            "/api/echo-cave",
            json_data={"document_id": echo_id, "content": content},
            token=token,
        )

    async def delete_echo(
        self, echo_id: str, *, user_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """删除用户自己的回声洞内容。"""
        return await self.request(
            "DELETE",
            "/api/echo-cave",
            json_data={"document_id": echo_id},
            token=token,
        )
