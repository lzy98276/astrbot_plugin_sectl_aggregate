"""回声洞投稿、查询、编辑和删除 API 客户端。"""

from __future__ import annotations

from typing import Any

from api.base import BaseApiClient


class EchoCaveApiClient(BaseApiClient):
    """提供回声洞核心资源的高层调用方法。"""

    async def health_check(self) -> str:
        response = await self.request("GET", "/")
        return str(response)[:200]

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
        """查询随机或指定编号的回声洞内容，返回单条文档。"""
        query = {"id": echo_id} if echo_id else {"mode": "random", "limit": 1}
        response = await self.request("GET", "/api/echo-cave", query=query)
        documents = response.get("documents")
        if isinstance(documents, list) and documents:
            doc = documents[0]
            return {
                "id": str(doc.get("sequence_number", "")),
                "content": doc.get("content", ""),
                "author": doc.get("author_id", "匿名"),
                "created_at": doc.get("created_at", ""),
                "document_id": doc.get("document_id", ""),
            }
        return {}

    async def get_echo_by_sequence(self, sequence_number: str) -> dict[str, Any]:
        """通过展示编号查询，返回完整文档信息（含 document_id）。"""
        response = await self.request("GET", "/api/echo-cave", query={"id": sequence_number})
        documents = response.get("documents")
        if isinstance(documents, list) and documents:
            doc = documents[0]
            return {
                "id": str(doc.get("sequence_number", "")),
                "content": doc.get("content", ""),
                "author": doc.get("author_id", "匿名"),
                "created_at": doc.get("created_at", ""),
                "document_id": doc.get("document_id", ""),
            }
        return {}

    async def get_my_echoes(self, qq_number: str, limit: int = 5) -> list[dict[str, Any]]:
        """查询指定 QQ 绑定用户的所有回声洞。"""
        response = await self.request(
            "GET", "/api/echo-cave", query={"author": qq_number, "limit": str(limit)}
        )
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            return []
        return [
            {
                "id": str(doc.get("sequence_number", "")),
                "content": doc.get("content", ""),
                "author": doc.get("author_id", "匿名"),
                "created_at": doc.get("created_at", ""),
                "document_id": doc.get("document_id", ""),
            }
            for doc in documents
        ]

    async def update_echo(
        self,
        document_id: str,
        content: str,
        *,
        user_id: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """更新用户自己的回声洞内容。"""
        return await self.request(
            "PUT",
            "/api/echo-cave",
            json_data={"document_id": document_id, "content": content},
            token=token,
        )

    async def delete_echo(
        self, document_id: str, *, user_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """删除用户自己的回声洞内容。"""
        return await self.request(
            "DELETE",
            "/api/echo-cave",
            json_data={"document_id": document_id},
            token=token,
        )
