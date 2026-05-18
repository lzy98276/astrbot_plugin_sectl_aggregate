"""回声洞 API 基础通信能力。"""

from __future__ import annotations

import asyncio
import json as _json
import traceback
from typing import Any

import aiohttp

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
        not_found_ok: bool = False,
    ) -> dict[str, Any]:
        """异步执行请求，并对瞬时网络错误进行有限重试。

        ``not_found_ok`` 为 ``True`` 时，服务端返回 404 不会抛出异常，
        而是返回空 ``dict``，适用于"未找到"属于正常业务状态的查询场景。
        """
        import logging
        logger = logging.getLogger("astrbot")

        url = f"{self.config.api_base_url}{path}"
        clean_query = _clean_mapping(query)
        req_headers = self._build_headers(token=token, extra_headers=headers)
        logger.info(
            f"发起 API 请求：{method.upper()} {url} "
            f"query={clean_query} headers={_summarize_headers(req_headers)}"
        )

        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            try:
                return await self._async_request(
                    method,
                    path,
                    json_data,
                    query,
                    token,
                    headers,
                    not_found_ok=not_found_ok,
                )
            except Exception as error:
                if not _should_retry_error(error):
                    raise EchoCaveApiError(_format_error(error)) from error
                last_error = error
                logger.warning(
                    f"API 请求第 {attempt + 1} 次失败 [{type(error).__name__}]: {error}\n"
                    f"Traceback: {traceback.format_exc()}"
                )
                if attempt >= self.config.retry_count:
                    break
                await asyncio.sleep(0.3 * (attempt + 1))
        raise EchoCaveApiError(f"API 请求失败：{_format_error(last_error)}") from last_error

    async def _async_request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None,
        query: dict[str, Any] | None,
        token: str | None,
        extra_headers: dict[str, str] | None,
        not_found_ok: bool = False,
    ) -> dict[str, Any]:
        """使用 aiohttp 异步发送 HTTP 请求。"""
        url = f"{self.config.api_base_url}{path}"

        headers = self._build_headers(token=token, extra_headers=extra_headers)
        clean_query = _clean_mapping(query)

        

        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method=method.upper(),
                url=url,
                params=clean_query or None,
                json=json_data,
                headers=headers,
            ) as response:
                if response.status >= 400:
                    if response.status == 404 and not_found_ok:
                        return {}
                    body = await response.text()
                    error_descriptions = _extract_error_descriptions(body)
                    if error_descriptions:
                        error_msg = (
                            f"HTTP {response.status} {_join_error_descriptions(error_descriptions)}"
                        )
                    else:
                        error_msg = (
                            f"HTTP {response.status} {response.reason or ''} "
                            f"from {method.upper()} {url}: {body[:200]}"
                        )
                    if response.status == 401:
                        error_msg += (
                            "。请检查插件配置中的 api_token 是否已填写有效的 "
                            "Appwrite JWT 或 API Key（管理后台生成）"
                        )
                    raise EchoCaveApiError(error_msg)
                response_body = await response.text()
                return self._parse_response(response_body)

    def _build_headers(
        self,
        *,
        token: str | None,
        extra_headers: dict[str, str] | None,
    ) -> dict[str, str]:
        """统一构建请求头，避免重复拼装逻辑。

        ``token`` 为 ``None`` 时使用配置中的 ``api_token``；
        传空字符串 ``""`` 表示**显式跳过认证头**（用于无需认证的端点）。
        """
        headers = {"Accept": "application/json"}
        if token is not None:
            auth_token = token
        else:
            auth_token = self.config.api_token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _parse_response(self, response_body: str) -> dict[str, Any]:
        """统一解析 JSON 响应，并兼容空响应场景。"""
        if not response_body.strip():
            return {"ok": True}
        try:
            data = _json.loads(response_body)
        except _json.JSONDecodeError as error:
            raise EchoCaveApiError("API 返回了非 JSON 内容") from error
        if isinstance(data, dict):
            if data.get("success") is False or data.get("ok") is False:
                message = data.get("message") or data.get("error") or "API 返回失败状态"
                raise EchoCaveApiError(str(message))
            return data
        return {"data": data}


def _format_error(error: Exception | None) -> str:
    """将异常转换为可读文本，处理 TimeoutError 等 __str__ 为空的情况。"""
    if error is None:
        return "未知错误"
    msg = str(error).strip()
    if msg:
        return msg
    type_name = type(error).__name__
    if type_name:
        return f"[{type_name}]"
    return "未知错误"


def _clean_mapping(values: dict[str, Any] | None) -> dict[str, Any]:
    """清理空查询参数，避免把空值发送给服务端。"""
    if not values:
        return {}
    return {key: value for key, value in values.items() if value not in (None, "")}


def _summarize_headers(headers: dict[str, str]) -> dict[str, str]:
    """生成安全的请求头摘要，避免在日志中泄露敏感信息。"""
    summary: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"authorization", "x-echo-cave-token"}:
            summary[key] = "<masked>" if value else "<empty>"
        else:
            summary[key] = value
    return summary


def _should_retry_error(error: Exception) -> bool:
    """仅对瞬时网络错误进行重试，避免重复放大业务失败。"""
    retryable_errors = (
        asyncio.TimeoutError,
        aiohttp.ClientConnectionError,
        aiohttp.ClientOSError,
        aiohttp.ServerTimeoutError,
        aiohttp.ServerDisconnectedError,
    )
    return isinstance(error, retryable_errors)


def _extract_error_descriptions(body: str) -> list[str]:
    """尝试从 API 错误响应 JSON 中提取用户友好的错误描述。

    优先取 ``error_description``，其次取 ``message``，最后取 ``error``。
    非 JSON 或无法解析时返回空列表。
    """
    try:
        data = _json.loads(body)
    except _json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    description = data.get("error_description")
    if description and isinstance(description, str) and description.strip():
        return [description.strip()]
    message = data.get("message")
    if message and isinstance(message, str) and message.strip():
        return [message.strip()]
    error = data.get("error")
    if error and isinstance(error, str) and error.strip():
        return [error.strip()]
    return []


def _join_error_descriptions(descriptions: list[str]) -> str:
    """将错误描述列表拼接为错误消息后缀。"""
    if not descriptions:
        return ""
    return " - " + " | ".join(descriptions)
