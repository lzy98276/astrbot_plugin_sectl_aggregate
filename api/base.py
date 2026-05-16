"""回声洞 API 基础通信能力。"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import EchoCaveConfig


class EchoCaveApiError(RuntimeError):
    """表示回声洞 API 调用失败。"""


class BaseApiClient:
    """封装通用 HTTP 请求、认证头和重试逻辑。"""

    def __init__(self, config: EchoCaveConfig):
        self.config = config

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """异步执行请求，并对瞬时网络错误进行有限重试。"""
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            try:
                return await asyncio.to_thread(
                    self._sync_request,
                    method,
                    path,
                    json_data,
                    query,
                    token,
                    headers,
                )
            except Exception as error:
                last_error = error
                if attempt >= self.config.retry_count:
                    break
                await asyncio.sleep(0.3 * (attempt + 1))
        raise EchoCaveApiError(f"API 请求失败：{last_error}") from last_error

    def _sync_request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None,
        query: dict[str, Any] | None,
        token: str | None,
        extra_headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        """使用标准库同步发送 HTTP 请求，减少额外依赖。"""
        import json

        url = f"{self.config.api_base_url}{path}"
        if query:
            clean_query = {
                key: value for key, value in query.items() if value not in (None, "")
            }
            if clean_query:
                url = f"{url}?{urlencode(clean_query)}"

        body = None
        headers = {"Accept": "application/json"}
        auth_token = token or self.config.api_token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if json_data is not None:
            body = json.dumps(json_data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if extra_headers:
            headers.update(extra_headers)

        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.config.request_timeout) as response:
                response_body = response.read().decode("utf-8")
                return self._parse_response(response_body)
        except Exception as error:
            raise EchoCaveApiError(str(error)) from error

    def _parse_response(self, response_body: str) -> dict[str, Any]:
        """统一解析 JSON 响应，并兼容空响应场景。"""
        import json

        if not response_body.strip():
            return {"ok": True}
        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise EchoCaveApiError("API 返回了非 JSON 内容") from error
        if isinstance(data, dict):
            if data.get("success") is False or data.get("ok") is False:
                message = data.get("message") or data.get("error") or "API 返回失败状态"
                raise EchoCaveApiError(str(message))
            return data
        return {"data": data}
