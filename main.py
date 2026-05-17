from __future__ import annotations

import sys
from pathlib import Path

# 确保插件目录在 sys.path 中，使 api/、config 等模块可被导入
_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

import re
from typing import AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from api.base import EchoCaveApiError
from api.echo_cave import EchoCaveApiClient
from api.qq_binding import QqBindingApiClient
from config import EchoCaveConfig
from renderer import HtmlTemplateRenderer
from state import AuthStateManager


@register(
    "astrbot_plugin_sectl_aggregate", "SECTL", "回声洞投稿、查询和 QQ 绑定插件", "1.0.0"
)
class EchoCavePlugin(Star):
    """回声洞 AstrBot 插件入口，负责指令路由和用户交互。"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = EchoCaveConfig.from_astrbot_config(config or {})
        self.echo_api = EchoCaveApiClient(self.config)
        self.binding_api = QqBindingApiClient(self.config)
        self.auth_state = AuthStateManager()
        self.renderer = HtmlTemplateRenderer(Path(__file__).parent / "templates")

    async def initialize(self):
        """插件初始化时记录当前 API 地址，便于排查部署配置。"""
        logger.info(f"回声洞插件已启动，API 地址：{self.config.api_base_url}")

    @filter.command("help")
    async def help_menu(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理独立 help 指令，返回插件功能菜单图片。"""
        try:
            yield await self._html_result(
                event, self.renderer.render_menu(), self.renderer.render_menu_text()
            )
        except Exception as error:
            logger.exception(f"help 指令处理异常：{error}")
            yield event.plain_result("帮助菜单暂时不可用，请稍后再试。")

    @filter.command("回声洞")
    async def echo_cave(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理回声洞主指令，支持 help、投稿、查看、编辑、删除和我的。"""
        command_text = _normalize_command(event.message_str)
        action, rest = _split_action(command_text)
        try:
            if action in ("", "help", "帮助", "菜单"):
                yield await self._html_result(
                    event, self.renderer.render_menu(), self.renderer.render_menu_text()
                )
                return
            if action == "投稿":
                async for _ in self._handle_create(event, rest):
                    yield _
                return
            if action == "查看":
                async for _ in self._handle_view(event, rest):
                    yield _
                return
            if action == "我的":
                async for _ in self._handle_my_echoes(event):
                    yield _
                return
            if action == "编辑":
                async for _ in self._handle_update(event, rest):
                    yield _
                return
            if action == "删除":
                async for _ in self._handle_delete(event, rest):
                    yield _
                return
            if action == "测试":
                yield await self._handle_test_api(event)
                return
            yield event.plain_result("未知回声洞指令，请发送：help")
        except EchoCaveApiError as error:
            logger.warning(f"回声洞 API 调用失败：{error}")
            yield event.plain_result(f"操作失败：{error}")
        except Exception as error:
            logger.exception(f"回声洞指令处理异常：{error}")
            yield event.plain_result("回声洞暂时没有回应，请稍后再试。")

    @filter.command("绑定")
    async def bind_qq(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理 QQ 绑定指令，指令格式为：绑定 QQ号 或 绑定 Key。"""
        command_text = _normalize_command(event.message_str)
        argument = command_text.removeprefix("绑定").strip()
        try:
            if not argument:
                yield event.plain_result("请发送：绑定 QQ号，用于申请 QQ 绑定 Key。")
                return
            if self.auth_state.get_pending(_get_user_id(event)) and not _is_qq_number(
                argument
            ):
                yield await self._handle_bind_confirm(event, argument)
                return
            async for _ in self._handle_bind_request(event, argument):
                yield _
        except EchoCaveApiError as error:
            logger.warning(f"QQ 绑定 API 调用失败：{error}")
            yield event.plain_result(f"绑定失败：{error}")
        except Exception as error:
            logger.exception(f"QQ 绑定处理异常：{error}")
            yield event.plain_result("绑定服务暂时不可用，请稍后再试。")

    @filter.command("绑定状态")
    async def binding_status(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理 QQ 绑定状态查询指令。"""
        try:
            status = await self.binding_api.get_status(_get_user_id(event))
            yield event.plain_result(self._format_binding_status(event, status))
        except EchoCaveApiError as error:
            logger.warning(f"QQ 绑定状态查询失败：{error}")
            yield event.plain_result(f"查询失败：{error}")
        except Exception as error:
            logger.exception(f"QQ 绑定状态处理异常：{error}")
            yield event.plain_result("查询服务暂时不可用，请稍后再试。")

    async def _handle_create(self, event: AstrMessageEvent, content: str):
        """处理投稿逻辑，写操作会先检查绑定状态。"""
        if not content:
            yield event.plain_result("请发送：回声洞 投稿 内容")
            return
        if not await self._ensure_bound(event):
            yield event.plain_result("投稿前请先完成 QQ 绑定：绑定 QQ号")
            return
        yield event.plain_result("正在投稿，请稍候...")
        response = await self.echo_api.create_echo(content, user_id=_get_user_id(event))
        echo_id = (
            _extract_response_value(
                response, "sequence_number", "document_id", "id", "echo_id"
            )
            or "新回声"
        )
        yield event.plain_result(f"投稿成功，回声洞编号：{echo_id}")

    async def _handle_view(self, event: AstrMessageEvent, echo_id: str):
        """处理随机或指定编号查询逻辑。"""
        yield event.plain_result("正在查询回声洞，请稍候...")
        response = await self.echo_api.get_echo(echo_id.strip() or None)
        if not response:
            yield event.plain_result("未找到回声洞。")
            return
        yield await self._html_result(
            event,
            self.renderer.render_echo(response),
            self.renderer.render_echo_text(response),
        )

    async def _handle_my_echoes(self, event: AstrMessageEvent):
        """查询当前用户投稿的回声洞列表。"""
        if not await self._ensure_bound(event):
            yield event.plain_result("请先完成 QQ 绑定：绑定 QQ号")
            return
        yield event.plain_result("正在查询你的回声洞，请稍候...")
        status = await self.binding_api.get_status(_get_user_id(event))
        qq_number = _extract_response_value(status, "qq_number", "qq") or ""
        if not qq_number:
            yield event.plain_result("未找到绑定的 QQ 号。")
            return
        echoes = await self.echo_api.get_my_echoes(qq_number)
        if not echoes:
            yield event.plain_result("你还没有投稿过回声洞。")
            return
        lines = [f"📣 你的回声洞（共 {len(echoes)} 条）：", ""]
        for echo in echoes:
            lines.append(f"#{echo['id']} {echo['content'][:50]}{'...' if len(echo['content']) > 50 else ''}")
            lines.append(f"   时间：{echo['created_at']}")
            lines.append("")
        yield event.plain_result("\n".join(lines))

    async def _html_result(
        self, event: AstrMessageEvent, html_content: str, fallback_text: str
    ):
        """优先使用 AstrBot HTML 渲染图片，失败时降级为纯文本。"""
        try:
            import asyncio
            image_url = await asyncio.wait_for(
                self.html_render(html_content, data={}, options={"full_page": True}),
                timeout=3.0,
            )
            return event.image_result(image_url)
        except asyncio.TimeoutError:
            logger.warning("HTML 渲染超时，改用纯文本。")
            return event.plain_result(fallback_text)
        except Exception as error:
            logger.warning(f"HTML 图片结果生成失败，改用纯文本：{error}")
            return event.plain_result(fallback_text)

    async def _handle_update(self, event: AstrMessageEvent, rest: str):
        """处理编辑逻辑，要求参数包含编号和新内容。"""
        echo_id, content = _split_first(rest)
        if not echo_id or not content:
            yield event.plain_result("请发送：回声洞 编辑 编号 新内容")
        if not await self._ensure_bound(event):
            yield event.plain_result("编辑前请先完成 QQ 绑定：绑定 QQ号")
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
        yield event.plain_result("正在更新，请稍候...")
        await self.echo_api.update_echo(echo_doc["document_id"], content, user_id=_get_user_id(event))
        yield event.plain_result(f"回声洞 #{echo_id} 已更新。")

    async def _handle_delete(self, event: AstrMessageEvent, echo_id: str):
        """处理删除逻辑，要求用户已经完成绑定。"""
        echo_id = echo_id.strip()
        if not echo_id:
            yield event.plain_result("请发送：回声洞 删除 编号")
        if not await self._ensure_bound(event):
            yield event.plain_result("删除前请先完成 QQ 绑定：绑定 QQ号")
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
        yield event.plain_result("正在删除，请稍候...")
        await self.echo_api.delete_echo(echo_doc["document_id"], user_id=_get_user_id(event))
        yield event.plain_result(f"回声洞 #{echo_id} 已删除。")

    async def _handle_test_api(self, event: AstrMessageEvent):
        url = self.config.api_base_url
        yield event.plain_result(f"正在测试 API 地址：{url}")
        try:
            result = await self.echo_api.health_check()
            yield event.plain_result(f"✅ API 连接成功！\r\n地址：{url}\r\n响应：{result}")
        except EchoCaveApiError as error:
            yield event.plain_result(f"❌ API 连接失败\r\n地址：{url}\r\n错误：{error}")
        except Exception as error:
            yield event.plain_result(f"❌ 测试过程出错\r\n地址：{url}\r\n错误：{error}")

    async def _handle_bind_request(self, event: AstrMessageEvent, qq: str):
        """申请绑定 Key，并缓存待确认状态。"""
        if not _is_qq_number(qq):
            yield event.plain_result("QQ 号格式不正确，请发送：绑定 QQ号")
        response = await self.binding_api.request_key(_get_user_id(event), qq)
        key = str(
            _extract_response_value(response, "temp_key", "key", "bind_key", "code")
            or ""
        )
        if key:
            self.auth_state.set_pending(_get_user_id(event), qq, key)
        message = (
            _extract_response_value(response, "message", "msg")
            or "绑定 Key 已生成，请按服务端提示完成确认。"
        )
        if key:
            message = f"{message}\n绑定 Key：{key}\n完成验证后发送：绑定 {key}"
        yield event.plain_result(str(message))

    async def _handle_bind_confirm(self, event: AstrMessageEvent, key: str):
        """确认绑定 Key，并刷新本地绑定状态。"""
        pending = self.auth_state.get_pending(_get_user_id(event))
        if not pending:
            return event.plain_result("请先发送：绑定 QQ号，申请临时 Key。")
        response = await self.binding_api.confirm(_get_user_id(event), pending.qq, key)
        self.auth_state.set_bound(_get_user_id(event), {"qq": pending.qq})
        message = _extract_response_value(response, "message", "msg") or "QQ 绑定成功。"
        return event.plain_result(str(message))

    async def _ensure_bound(self, event: AstrMessageEvent) -> bool:
        """优先使用缓存，缓存缺失时调用服务端确认绑定状态。"""
        user_id = _get_user_id(event)
        if self.auth_state.is_bound(user_id):
            return True
        status = await self.binding_api.get_status(user_id)
        if _is_bound_status(status):
            self.auth_state.set_bound(
                user_id,
                {
                    "qq": str(
                        _extract_response_value(status, "qq_number", "qq") or "已绑定"
                    )
                },
            )
            return True
        self.auth_state.clear_bound(user_id)
        return False

    def _format_binding_status(self, event: AstrMessageEvent, status: dict) -> str:
        """格式化绑定状态，并同步本地缓存。"""
        user_id = _get_user_id(event)
        if _is_bound_status(status):
            qq = str(_extract_response_value(status, "qq_number", "qq") or "已绑定")
            self.auth_state.set_bound(user_id, {"qq": qq})
            return f"当前账号已绑定 QQ：{qq}"
        self.auth_state.clear_bound(user_id)
        pending = self.auth_state.get_pending(user_id)
        if pending:
            return f"当前账号未完成绑定，待确认 QQ：{pending.qq}。请发送：绑定 {pending.key}"
        return "当前账号尚未绑定 QQ，请发送：绑定 QQ号"

    async def terminate(self):
        """插件卸载时记录资源清理日志。"""
        logger.info("回声洞插件已停止。")


def _normalize_command(message: str) -> str:
    """统一去除命令前缀，兼容带斜杠和不带斜杠的中文指令。"""
    return (message or "").strip().removeprefix("/").strip()


def _split_action(command_text: str) -> tuple[str, str]:
    """拆分回声洞二级指令和剩余参数。"""
    text = command_text.removeprefix("回声洞").strip()
    return _split_first(text)


def _split_first(text: str) -> tuple[str, str]:
    """按首个空白字符拆分文本。"""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _get_user_id(event: AstrMessageEvent) -> str:
    """从事件中提取稳定用户标识，兼容不同平台事件结构。"""
    sender_id = getattr(event, "get_sender_id", None)
    if callable(sender_id):
        value = sender_id()
        if value:
            return str(value)
    message_obj = getattr(event, "message_obj", None)
    for attr in ("sender_id", "user_id"):
        value = getattr(message_obj, attr, None)
        if value:
            return str(value)
    raise ValueError("无法从事件中获取用户ID")


def _is_qq_number(value: str) -> bool:
    """校验 QQ 号格式，避免误把其它文本当成绑定申请。"""
    return bool(re.fullmatch(r"[1-9]\d{4,11}", value.strip()))


def _extract_response_value(response: dict, *keys: str):
    """从常见 API 响应层级中提取字段值。"""
    for source in (
        response,
        response.get("data") if isinstance(response, dict) else None,
        response.get("document") if isinstance(response, dict) else None,
        response.get("binding") if isinstance(response, dict) else None,
    ):
        if isinstance(source, dict):
            for key in keys:
                if key in source and source[key] not in (None, ""):
                    return source[key]
    return None


def _is_bound_status(status: dict) -> bool:
    """兼容多种绑定状态字段命名。"""
    value = _extract_response_value(status, "bound", "is_bound", "bind", "status")
    return value is True or str(value).lower() in {
        "true",
        "bound",
        "binded",
        "绑定",
        "已绑定",
        "1",
    }
