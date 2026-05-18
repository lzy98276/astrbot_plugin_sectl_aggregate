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

DEFAULT_MY_ECHO_LIMIT = 20
VIEW_MODE_ALIASES = {"最新": "最新", "列表": "列表", "随机": "随机", "latest": "最新", "list": "列表", "random": "随机"}


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
        """查看根目录帮助菜单"""
        try:
            fallback = self.renderer.render_root_menu_text()
        except Exception as error:
            logger.warning(f"根菜单纯文本渲染失败，使用硬编码降级：{error}")
            fallback = (
                "📣 黎悠看板娘指令菜单\r\n"
                "help：查看帮助菜单\r\n"
                "回声洞 帮助：查看回声洞帮助菜单\r\n"
                "绑定 [临时Key]：使用 Key 完成 QQ 绑定\r\n"
                "绑定状态：查看绑定状态"
            )
        try:
            html = self.renderer.render_root_menu()
        except Exception as error:
            logger.warning(f"帮助菜单 HTML 模板渲染失败，使用纯文本降级：{error}")
            yield event.plain_result(fallback)
            return
        # _html_result 内部已有完善的 try/except 降级到纯文本
        yield await self._html_result(event, html, fallback)

    @filter.command("回声洞")
    async def echo_cave(self, event: AstrMessageEvent) -> AsyncGenerator:
        """回声洞主指令：投稿、查看（随机/编号/最新/列表）、编辑、删除、我的"""
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
            yield event.plain_result("未知回声洞指令，请发送：help")
        except EchoCaveApiError as error:
            logger.warning(f"回声洞 API 调用失败：{error}")
            yield event.plain_result("操作失败，请稍后重试或联系管理员。")
        except Exception as error:
            logger.exception(f"回声洞指令处理异常：{error}")
            yield event.plain_result("回声洞暂时没有回应，请稍后再试。")

    @filter.command("绑定")
    async def bind_qq(self, event: AstrMessageEvent) -> AsyncGenerator:
        """确认绑定，格式：绑定 [临时Key]"""
        command_text = _normalize_command(event.message_str)
        argument = command_text.removeprefix("绑定").strip()
        try:
            if not argument:
                yield event.plain_result("请发送：绑定 [临时Key]")
                return
            yield event.plain_result(await self._handle_bind_confirm(event, argument))
        except EchoCaveApiError as error:
            logger.warning(f"QQ 绑定 API 调用失败：{error}")
            yield event.plain_result(f"绑定失败：{error}")
        except Exception as error:
            logger.exception(f"QQ 绑定处理异常：{error}")
            yield event.plain_result("绑定服务暂时不可用，请稍后再试。")

    @filter.command("绑定状态")
    async def binding_status(self, event: AstrMessageEvent) -> AsyncGenerator:
        """查看当前 QQ 绑定状态"""
        try:
            qq_number = _get_user_id(event)
            status = await self.binding_api.get_status(
                qq_number, token=self.config.api_token or None
            )
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

    async def _handle_view(self, event: AstrMessageEvent, rest: str):
        parts = rest.strip().split()
        if not parts:
            async for _ in self._view_random(event):
                yield _
            return

        mode = VIEW_MODE_ALIASES.get(parts[0], parts[0])

        if mode.isdigit():
            async for _ in self._view_by_id(event, mode):
                yield _
            return

        if mode in ("最新", "列表", "随机"):
            count, page = _parse_view_pagination(parts[1:])
            if mode == "最新":
                async for _ in self._view_latest(event, count, page):
                    yield _
            elif mode == "列表":
                async for _ in self._view_list(event, count, page):
                    yield _
            else:
                async for _ in self._view_random_batch(event, count):
                    yield _
            return

        async for _ in self._view_by_id(event, mode):
            yield _

    async def _view_random(self, event: AstrMessageEvent):
        yield event.plain_result("正在查询回声洞，请稍候...")
        response = await self.echo_api.get_echo()
        if not response:
            yield event.plain_result("未找到回声洞。")
            return
        yield await self._html_result(
            event,
            self.renderer.render_echo(response),
            self.renderer.render_echo_text(response),
        )

    async def _view_random_batch(self, event: AstrMessageEvent, count: int):
        """批量随机查看多条回声洞。"""
        # API 文档：随机模式 limit 最大 5
        count = min(count, 5)
        yield event.plain_result("正在随机查询回声洞，请稍候...")
        echoes, total = await self.echo_api.get_echoes(mode="random", limit=count, offset=0)
        if not echoes:
            yield event.plain_result("未找到回声洞。")
            return
        yield event.plain_result(self._format_echo_batch("随机", echoes, total, 1, count))

    async def _view_by_id(self, event: AstrMessageEvent, echo_id: str):
        yield event.plain_result("正在查询回声洞，请稍候...")
        response = await self.echo_api.get_echo(echo_id)
        if not response:
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
            return
        yield await self._html_result(
            event,
            self.renderer.render_echo(response),
            self.renderer.render_echo_text(response),
        )

    async def _view_latest(self, event: AstrMessageEvent, count: int, page: int):
        yield event.plain_result("正在查询最新回声洞，请稍候...")
        offset = (page - 1) * count
        echoes, total = await self.echo_api.get_echoes(mode="latest", limit=count, offset=offset)
        if not echoes:
            yield event.plain_result("暂无回声洞。")
            return
        yield event.plain_result(self._format_echo_batch("最新", echoes, total, page, count))

    async def _view_list(self, event: AstrMessageEvent, count: int, page: int):
        yield event.plain_result("正在加载回声洞列表，请稍候...")
        offset = (page - 1) * count
        echoes, total = await self.echo_api.get_echoes(mode="latest", limit=count, offset=offset)
        if not echoes:
            yield event.plain_result("暂无回声洞。")
            return
        yield event.plain_result(self._format_echo_batch("列表", echoes, total, page, count))

    async def _handle_my_echoes(self, event: AstrMessageEvent):
        """查询当前用户投稿的回声洞列表。"""
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("请先完成 QQ 绑定：绑定 QQ号")
            return
        yield event.plain_result("正在查询你的回声洞，请稍候...")
        # _ensure_bound 已缓存绑定状态，直接从缓存取 QQ 号
        bound = self.auth_state.get_bound(user_id)
        qq_number = (bound or {}).get("qq", "") if bound else ""
        if not qq_number:
            yield event.plain_result("未找到绑定的 QQ 号。")
            return
        echoes = await self.echo_api.get_my_echoes(qq_number, limit=DEFAULT_MY_ECHO_LIMIT)
        if not echoes:
            yield event.plain_result("你还没有投稿过回声洞。")
            return
        lines = [f"📣 你的回声洞（共 {len(echoes)} 条）：", ""]
        for echo in echoes:
            lines.append(f"#{echo['id']} {echo['content'][:50]}{'...' if len(echo['content']) > 50 else ''}")
            lines.append(f"   时间：{echo['created_at']}")
            lines.append("")
        yield event.plain_result("\r\n".join(lines))

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
        echo_id, content = _split_first(rest)
        if not echo_id or not content:
            yield event.plain_result("请发送：回声洞 编辑 编号 新内容")
            return
        if not await self._ensure_bound(event):
            yield event.plain_result("编辑前请先完成 QQ 绑定：绑定 QQ号")
            return
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
            return
        yield event.plain_result("正在更新，请稍候...")
        await self.echo_api.update_echo(echo_doc["document_id"], content, user_id=_get_user_id(event))
        yield event.plain_result(f"回声洞 #{echo_id} 已更新。")

    async def _handle_delete(self, event: AstrMessageEvent, echo_id: str):
        echo_id = echo_id.strip()
        if not echo_id:
            yield event.plain_result("请发送：回声洞 删除 编号")
            return
        if not await self._ensure_bound(event):
            yield event.plain_result("删除前请先完成 QQ 绑定：绑定 QQ号")
            return
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
            return
        yield event.plain_result("正在删除，请稍候...")
        await self.echo_api.delete_echo(echo_doc["document_id"], user_id=_get_user_id(event))
        yield event.plain_result(f"回声洞 #{echo_id} 已删除。")

    def _format_echo_batch(
        self, mode: str, echoes: list[dict], total: int, page: int, per_page: int
    ) -> str:
        total_pages = max(1, (total + per_page - 1) // per_page)
        lines = [f"📣 回声洞 {mode}（共 {total} 条，第 {page}/{total_pages} 页）", "━━━━━━━━━━━━━━"]
        for echo in echoes:
            preview = echo["content"][:60]
            if len(echo["content"]) > 60:
                preview += "..."
            lines.append(f"#{echo['id']} {preview}")
            lines.append(f"   发布者：{echo['author']} | {echo['created_at']}")
            lines.append("")
        if page < total_pages:
            lines.append("━━━━━━━━━━━━━━")
            lines.append(f"发送「回声洞 查看 {mode} 第{page + 1}页」查看更多")
        return "\r\n".join(lines)

    async def _handle_bind_confirm(self, event: AstrMessageEvent, key: str) -> str:
        """确认绑定 Key，并刷新本地绑定状态。"""
        user_id = _get_user_id(event)
        # 在 QQ 平台上下文中，sender_id 即为 QQ 号
        response = await self.binding_api.confirm(user_id, user_id, key)
        status = await self.binding_api.get_status(
            user_id, token=self.config.api_token or None
        )
        if _is_bound_status(status):
            qq = str(_extract_response_value(status, "qq_number", "qq") or user_id)
            self.auth_state.set_bound(user_id, {"qq": qq})
        else:
            raise EchoCaveApiError("绑定确认已提交，但服务端仍未返回已绑定状态，请稍后重试。")
        return str(_extract_response_value(response, "message", "msg") or "QQ 绑定成功。")
        if _is_bound_status(status):
            qq = str(_extract_response_value(status, "qq_number", "qq") or user_id)
            self.auth_state.set_bound(user_id, {"qq": qq})
        else:
            raise EchoCaveApiError("绑定确认已提交，但服务端仍未返回已绑定状态，请稍后重试。")
        return str(_extract_response_value(response, "message", "msg") or "QQ 绑定成功。")

    async def _ensure_bound(self, event: AstrMessageEvent) -> bool:
        """优先使用缓存，缓存缺失时调用服务端确认绑定状态。

        API 认证失败等异常会被静默捕获并当作"未绑定"处理，
        避免原始 HTTP 错误暴露给用户。
        """
        user_id = _get_user_id(event)
        if self.auth_state.is_bound(user_id):
            return True
        try:
            status = await self.binding_api.get_status(
                user_id, token=self.config.api_token or None
            )
        except EchoCaveApiError as error:
            logger.warning(f"查询绑定状态失败，按未绑定处理：{error}")
            self.auth_state.clear_bound(user_id)
            return False
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
        return "当前账号尚未绑定 QQ"

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


def _parse_view_pagination(tokens: list[str]) -> tuple[int, int]:
    """解析最新/列表指令中的数量和页码参数。"""
    count = 1
    page = 1
    for token in tokens:
        if token.isdigit():
            count = min(max(int(token), 1), 10)
            continue
        normalized_token = token.removeprefix("页").removesuffix("页")
        if normalized_token.startswith("第"):
            normalized_token = normalized_token[1:]
        if normalized_token.isdigit():
            page = max(int(normalized_token), 1)
    return count, page


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
