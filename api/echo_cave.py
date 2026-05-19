"""回声洞投稿、查询、编辑和删除 API 客户端。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from api.base import BaseApiClient, EchoCaveApiError


def _format_utc8(iso_string: str) -> str:
    """将 ISO8601 UTC 时间字符串转换为 UTC+8 可读格式。
    
    传入空字符串或无效格式时原样返回。
    """
    if not iso_string:
        return iso_string
    try:
        if iso_string.endswith("Z"):
            iso_string = iso_string[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc8 = dt.astimezone(timezone(timedelta(hours=8)))
        return dt_utc8.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_string


class EchoCaveApiClient(BaseApiClient):
    """提供回声洞核心资源的高层调用方法。"""

    async def health_check(self) -> str:
        response = await self.request(
            "GET", "/api/echo-cave", query={"mode": "random", "limit": "1"}
        )
        docs = response.get("documents", [])
        count = len(docs) if isinstance(docs, list) else 0
        return f"API 正常，文档总数：{response.get('total', '未知')}，返回 {count} 条"

    async def create_echo(
        self, content: str, *, user_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """提交一条新的回声洞内容。

        内部投稿接口依赖 x-echo-cave-token（即 api_token），
        未配置时直接报错避免无效请求。
        """
        if not self.config.api_token:
            raise EchoCaveApiError(
                "投稿失败：插件配置中的 api_token 未设置，"
                "请联系管理员配置 Token"
            )
        return await self.request(
            "POST",
            "/api/echo-cave/internal",
            json_data={"content": content, "author_id": user_id},
            query={"token": self.config.api_token},
            token="",
        )

    async def get_echo(self, echo_id: str | None = None) -> dict[str, Any]:
        """查询随机或指定编号的回声洞内容，返回单条文档。

        按编号查询时若服务端返回 404（不存在），返回空 ``dict``，
        由调用方通过 ``if not response:`` 判断。
        """
        query = {"id": echo_id} if echo_id else {"mode": "random", "limit": 1}
        not_found_ok = bool(echo_id)
        response = await self.request(
            "GET", "/api/echo-cave", query=query, not_found_ok=not_found_ok
        )
        return _first_echo_document(response)

    async def get_echoes(
        self,
        *,
        mode: str = "latest",
        limit: int = 10,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, str] = {"limit": str(limit)}
        # API 文档中 `mode` 仅支持 "random"，其他模式不传参让 API 使用默认行为
        if mode == "random":
            query["mode"] = "random"
        response = await self.request("GET", "/api/echo-cave", query=query)
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            documents = []
        total = int(response.get("total", len(documents)))
        return (
            [
                _normalize_echo_document(doc)
                for doc in documents
            ],
            total,
        )

    async def get_echo_by_sequence(self, sequence_number: str) -> dict[str, Any]:
        """通过展示编号查询，返回完整文档信息（含 document_id）。

        不存在时返回空 ``dict``，由调用方通过 ``if not response:`` 判断。
        """
        response = await self.request(
            "GET", "/api/echo-cave", query={"id": sequence_number}, not_found_ok=True
        )
        return _first_echo_document(response)

    async def get_my_echoes(
        self, qq_number: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """查询指定 QQ 用户的所有回声洞（内部 API）。"""
        response = await self.request(
            "GET",
            "/api/echo-cave/internal",
            query={"qq_number": qq_number, "limit": str(limit), "token": self.config.api_token},
            token="",
        )
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            return []
        return [_normalize_echo_document(doc) for doc in documents]

    async def update_echo(
        self,
        document_id: str,
        content: str,
        *,
        qq_number: str,
    ) -> dict[str, Any]:
        """更新回声洞（内部 API）。"""
        return await self.request(
            "PUT",
            "/api/echo-cave/internal",
            json_data={
                "document_id": document_id,
                "content": content,
                "qq_number": qq_number,
            },
            query={"token": self.config.api_token},
            token="",
        )

    async def delete_echo(
        self, document_id: str, *, qq_number: str
    ) -> dict[str, Any]:
        """删除回声洞（内部 API）。"""
        return await self.request(
            "DELETE",
            "/api/echo-cave/internal",
            json_data={"document_id": document_id, "qq_number": qq_number},
            query={"token": self.config.api_token},
            token="",
        )


def _first_echo_document(response: dict[str, Any]) -> dict[str, Any]:
    """从文档列表中提取第一条回声洞，便于单条查询复用。"""
    documents = response.get("documents")
    if isinstance(documents, list) and documents:
        return _normalize_echo_document(documents[0])
    return {}


def _normalize_echo_document(doc: dict[str, Any]) -> dict[str, Any]:
    """统一回声洞文档字段，减少各接口重复映射逻辑。

    API 响应中 ``author_name`` 为平台显示名称（如用户名），
    ``author_id`` 为内部 Appwrite 文档 ID，显示时优先使用 ``author_name``。
    """
    return {
        "id": str(doc.get("sequence_number", "")),
        "content": doc.get("content", ""),
        "author": doc.get("author_name") or doc.get("author_id", "匿名"),
        "created_at": _format_utc8(doc.get("created_at", "")),
        "document_id": doc.get("document_id", ""),
    }
