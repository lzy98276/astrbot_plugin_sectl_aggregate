"""Hub 内容中心投稿、查询、编辑和删除 API 客户端。"""

from __future__ import annotations

from typing import Any

from api.base import BaseApiClient, EchoCaveApiError


class HubApiClient(BaseApiClient):
    """提供 Hub 内容中心核心资源的高层调用方法。"""

    async def create_hub(
        self,
        title: str,
        description: str,
        *,
        author_id: str,
        author_name: str = "",
        tags: list[str] | None = None,
        image_data: str | None = None,
        image_filename: str | None = None,
    ) -> dict[str, Any]:
        """投稿 Hub 内容（内部 API）。

        Args:
            title: 标题。
            description: 描述。
            author_id: 作者 ID。
            author_name: 作者显示名。
            tags: 标签列表。
            image_data: Base64 图片数据，格式 'data:image/{ext};base64,...'。
            image_filename: 文件名（不含扩展名），仅在 image_data 模式有效。
        """
        if not self.config.api_token:
            raise EchoCaveApiError(
                "投稿失败：插件配置中的 api_token 未设置，"
                "请联系管理员配置 Token"
            )
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "author_id": author_id,
        }
        if author_name:
            body["author_name"] = author_name
        if tags:
            body["tags"] = tags
        if image_data:
            body["image_data"] = image_data
        if image_filename:
            body["image_filename"] = image_filename
        body["status"] = "approved"
        return await self.request(
            "POST",
            "/api/hub/internal",
            json_data=body,
            token="",
            query={"token": self.config.effective_hub_token},
        )

    async def get_hub(self, hub_id: str | None = None) -> dict[str, Any]:
        """查询随机或指定编号的 Hub 内容，返回单条文档。"""
        query = {"id": hub_id} if hub_id else {"mode": "random", "limit": 1}
        not_found_ok = bool(hub_id)
        response = await self.request(
            "GET", "/api/hub", query=query, not_found_ok=not_found_ok
        )
        return _first_hub_document(response)

    async def get_hubs(
        self,
        *,
        mode: str = "latest",
        limit: int = 10,
        offset: int = 0,
        keyword: str | None = None,
        tag: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询 Hub 内容列表。"""
        query: dict[str, str] = {"limit": str(limit)}
        if mode == "random":
            query["mode"] = "random"
        if keyword:
            query["keyword"] = keyword
        if tag:
            query["tag"] = tag
        if sort:
            query["sort"] = sort
        if offset:
            query["offset"] = str(offset)
        response = await self.request("GET", "/api/hub", query=query)
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            documents = []
        total = int(response.get("total", len(documents)))
        return [_normalize_hub_document(doc) for doc in documents], total

    async def get_my_hubs(
        self, author_id: str, status: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """查询当前用户自己的 Hub 投稿。"""
        query: dict[str, str] = {"mine": "true", "limit": str(limit)}
        if status:
            query["status"] = status
        response = await self.request(
            "GET",
            "/api/hub",
            query=query,
            token=self.config.api_token or None,
        )
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            return []
        return [_normalize_hub_document(doc) for doc in documents]

    async def get_hub_by_sequence(self, sequence_number: str) -> dict[str, Any]:
        """通过展示编号查询 Hub 内容，返回完整文档信息。"""
        response = await self.request(
            "GET", "/api/hub", query={"id": sequence_number}, not_found_ok=True
        )
        return _first_hub_document(response)

    async def get_tags(self) -> list[dict[str, Any]]:
        """获取 Hub 标签列表。"""
        response = await self.request("GET", "/api/hub", query={"tags": "true"})
        tags = response.get("tags", [])
        return tags if isinstance(tags, list) else []

    async def get_count(self) -> int:
        """获取 Hub 内容总数。"""
        response = await self.request("GET", "/api/hub", query={"count": "true"})
        return int(response.get("count", 0))

    async def update_hub(
        self,
        document_id: str,
        title: str,
        description: str,
        *,
        author_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """更新 Hub 内容（内部 API）。"""
        body: dict[str, Any] = {
            "document_id": document_id,
            "title": title,
            "description": description,
        }
        if tags:
            body["tags"] = tags
        return await self.request(
            "PUT",
            "/api/hub/internal",
            json_data=body,
            token="",
            query={"token": self.config.effective_hub_token},
        )

    async def delete_hub(
        self, document_id: str, *, author_id: str | None = None
    ) -> dict[str, Any]:
        """删除 Hub 内容（内部 API）。"""
        body: dict[str, Any] = {"document_id": document_id}
        if author_id:
            body["author_id"] = author_id
        return await self.request(
            "DELETE",
            "/api/hub/internal",
            json_data=body,
            token="",
            query={"token": self.config.effective_hub_token},
        )


def _first_hub_document(response: dict[str, Any]) -> dict[str, Any]:
    """从文档列表中提取第一条 Hub 内容。"""
    documents = response.get("documents")
    if isinstance(documents, list) and documents:
        return _normalize_hub_document(documents[0])
    return {}


def _normalize_hub_document(doc: dict[str, Any]) -> dict[str, Any]:
    """统一 Hub 文档字段。"""
    return {
        "id": str(doc.get("sequence_number", "")),
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "image_url": doc.get("image_url", ""),
        "thumbnail_url": doc.get("thumbnail_url", ""),
        "author": doc.get("author_name") or doc.get("author_id", "匿名"),
        "author_id": doc.get("author_id", ""),
        "tags": doc.get("tags", []),
        "status": doc.get("status", ""),
        "created_at": doc.get("created_at", ""),
        "published_at": doc.get("published_at", ""),
        "views": int(doc.get("views", 0)),
        "like_count": int(doc.get("like_count", 0)),
        "document_id": doc.get("document_id", ""),
    }
