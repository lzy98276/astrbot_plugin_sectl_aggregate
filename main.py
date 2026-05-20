from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# 确保插件目录在 sys.path 中，使 api/、config 等模块可被导入
_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

import os
import re
import tempfile
import time
from typing import AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Node, Nodes, Plain

from api.base import EchoCaveApiError
from api.echo_cave import EchoCaveApiClient
from api.hub import HubApiClient
from api.qq_binding import QqBindingApiClient
from config import EchoCaveConfig
from renderer import HtmlTemplateRenderer
from state import AuthStateManager

MAX_BATCH_LIMIT = 30
MERGE_FORWARD_THRESHOLD = 3
VIEW_MODE_ALIASES = {"最新": "最新", "随机": "随机", "latest": "最新", "random": "随机"}
PENDING_HUB_SUBMISSIONS: dict[str, dict] = {}



def _format_time(iso_str: str) -> str:
    """将 ISO 8601 时间转为 UTC+8 可读格式。"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=None) + timedelta(hours=8)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


def _detect_image_ext(data: bytes) -> str:
    """从图片字节数据检测文件扩展名。"""
    if data[:8] == b"\x89PNG\r\n\x1a":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpeg"


async def _extract_image_base64(event: AstrMessageEvent) -> tuple[str | None, str | None]:
    """从消息中提取图片，返回 (base64_data, filename)。

    base64_data 格式：'data:image/{ext};base64,{encoded}'。
    如果消息中没有图片，返回 (None, None)。
    """
    import base64

    message_obj = getattr(event, "message_obj", None)
    if not message_obj:
        return None, None
    message = getattr(message_obj, "message", None)
    if not message:
        return None, None
    log_hint = []
    try:
        for comp in message:
            comp_type = type(comp).__name__
            log_hint.append(comp_type)
            # 按实际类型名判断，不依赖 import 的类引用
            is_image = comp_type == "Image"
            if not is_image:
                # 补充检查：带 file 属性且看起来是图片路径/URL
                file_attr = getattr(comp, "file", None) or getattr(comp, "url", None) or ""
                if isinstance(file_attr, str) and (
                    file_attr.startswith(("http://", "https://"))
                    or file_attr.startswith(("/", "\\"))
                    or file_attr.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                ):
                    is_image = True
            if not is_image:
                continue
            # 优先使用 URL（aiocqhttp 提供可下载链接），其次使用本地文件路径
            file_attr = getattr(comp, "url", None) or getattr(comp, "file", None)
            if not file_attr:
                logger.warning(f"图片组件缺少 url 或 file 属性")
                continue
            if file_attr.startswith(("http://", "https://")):
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        file_attr, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"下载图片失败 HTTP {resp.status}: {file_attr}")
                            continue
                        data = await resp.read()
            else:
                # 本地文件，跳过无法访问的相对路径
                if not os.path.isabs(file_attr):
                    logger.warning(f"图片文件路径非绝对路径，跳过：{file_attr}")
                    continue
                with open(file_attr, "rb") as f:
                    data = f.read()
            ext = _detect_image_ext(data)
            encoded = base64.b64encode(data).decode("utf-8")
            return f"data:image/{ext};base64,{encoded}", f"hub_upload.{ext}"
    except Exception as exc:
        logger.warning(f"提取消息图片失败，消息组件：{log_hint}，错误：{exc}")
    return None, None


@register(
    "astrbot_plugin_sectl_aggregate", "SECTL", "回声洞投稿、查询和 QQ 绑定插件", "1.0.0"
)
class EchoCavePlugin(Star):
    """回声洞 AstrBot 插件入口，负责指令路由和用户交互。"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = EchoCaveConfig.from_astrbot_config(config or {})
        self.echo_api = EchoCaveApiClient(self.config)
        self.hub_api = HubApiClient(self.config)
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
                "/help：查看帮助菜单\r\n"
                "/回声洞 帮助：查看回声洞帮助菜单\r\n"
                "/hub 帮助：查看 Hub 内容中心帮助菜单\r\n"
                "/绑定 [临时Key]：使用 Key 完成 QQ 绑定\r\n"
                "/解绑：解绑当前 QQ 账号\r\n"
                "/绑定状态：查看绑定状态"
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
        """回声洞主指令：投稿、查看（随机/编号/最新）、编辑、删除、我的"""
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

    @filter.command("解绑")
    async def unbind_qq(self, event: AstrMessageEvent) -> AsyncGenerator:
        """解绑当前 QQ 账号"""
        try:
            user_id = _get_user_id(event)
            if not await self._ensure_bound(event):
                yield event.plain_result("你当前没有绑定 QQ 账号。")
                return
            await self.binding_api.unbind(user_id)
            self.auth_state.clear_bound(user_id)
            yield event.plain_result("QQ 账号已解绑。")
        except EchoCaveApiError as error:
            logger.warning(f"QQ 解绑 API 调用失败：{error}")
            yield event.plain_result(f"解绑失败：{error}")
        except Exception as error:
            logger.exception(f"QQ 解绑处理异常：{error}")
            yield event.plain_result("解绑服务暂时不可用，请稍后再试。")

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

    @filter.command("hub")
    async def hub(self, event: AstrMessageEvent) -> AsyncGenerator:
        """Hub 内容中心主指令：投稿（附带图片）、查看、标签、编辑、删除"""
        command_text = _normalize_command(event.message_str)
        action, rest = _split_hub_action(command_text)
        try:
            if action in ("", "help", "帮助", "菜单"):
                if action == "":
                    async for _ in self._try_complete_pending(event):
                        yield _
                        return
                yield await self._html_result(
                    event, self.renderer.render_hub_menu(), self.renderer.render_hub_menu_text()
                )
                return
            if action == "投稿":
                async for _ in self._handle_hub_create(event, rest):
                    yield _
                return
            if action == "投稿取消":
                user_id = _get_user_id(event)
                if PENDING_HUB_SUBMISSIONS.pop(user_id, None):
                    yield event.plain_result("已取消投稿。")
                else:
                    yield event.plain_result("当前没有待取消的投稿。")
                return
            if action == "查看":
                async for _ in self._handle_hub_view(event, rest):
                    yield _
                return
            if action in ("标签", "tags"):
                async for _ in self._handle_hub_tags(event):
                    yield _
                return
            if action == "编辑":
                async for _ in self._handle_hub_update(event, rest):
                    yield _
                return
            if action == "删除":
                async for _ in self._handle_hub_delete(event, rest):
                    yield _
                return
            yield event.plain_result("未知 hub 指令，请发送：hub 帮助")
        except EchoCaveApiError as error:
            logger.warning(f"Hub API 调用失败：{error}")
            yield event.plain_result("操作失败，请稍后重试或联系管理员。")
        except Exception as error:
            logger.exception(f"Hub 指令处理异常：{error}")
            yield event.plain_result("Hub 服务暂时没有回应，请稍后再试。")

    async def on_message(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理非指令消息：检测待提交用户的下一条消息。
        有图片则自动完成投稿，无图片（纯文字）则自动取消，60秒超时。"""
        user_id = _get_user_id(event)
        if not PENDING_HUB_SUBMISSIONS.get(user_id):
            return
        async for _ in self._try_complete_pending(event):
            yield _

    async def _download_image(self, url: str) -> str | None:
        """下载图片到临时文件，返回文件路径。"""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
                    ext = ".jpg"
                    ct = resp.content_type or ""
                    if "png" in ct:
                        ext = ".png"
                    elif "gif" in ct:
                        ext = ".gif"
                    elif "webp" in ct:
                        ext = ".webp"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    tmp.write(data)
                    tmp.close()
                    return tmp.name
        except Exception as error:
            logger.warning(f"Hub 图片下载失败：{error}")
            return None

    async def _send_hub_with_image(self, event: AstrMessageEvent, hub_data: dict) -> AsyncGenerator:
        """发送 Hub 内容，图片放在标题下方。"""
        hub_id = hub_data.get("id", "")
        title = hub_data.get("title", "")
        description = hub_data.get("description", "")
        tags = hub_data.get("tags", [])
        author = hub_data.get("author", "匿名")
        created_at = hub_data.get("created_at", "")
        views = hub_data.get("views", 0)
        before_img = f"📣 Hub #{hub_id}\r\n标题：{title}"
        rest_lines = [f"描述：{description}"]
        if tags:
            rest_lines.append(f"标签：{' '.join(tags)}")
        rest_lines.append(f"发布者：{author}")
        time_str = _format_time(created_at) if created_at else ""
        if time_str:
            rest_lines.append(time_str)
        rest_lines.append(f"浏览量：{views}")
        after_img = "\r\n".join(rest_lines)
        image_url = hub_data.get("image_url", "")
        if image_url:
            file_path = await self._download_image(image_url)
            if file_path:
                yield event.chain_result([Plain(before_img), Image(file=file_path), Plain(after_img)])
                try:
                    os.unlink(file_path)
                except Exception:
                    pass
                return
        yield event.plain_result(f"{before_img}\r\n{after_img}")

    async def _handle_hub_create(self, event: AstrMessageEvent, rest: str):
        """处理 Hub 投稿。带图则一段式提交，无图则保存待提交等待后续图片。"""
        if not rest:
            yield event.plain_result("请发送：hub 投稿 [标题] | [描述]")
            return
        parts = rest.split("|", 1)
        title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        if not title:
            yield event.plain_result("请发送：hub 投稿 [标题] | [描述]")
            return
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("投稿前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        bound = self.auth_state.get_bound(user_id)
        sectl_user_id = (bound or {}).get("sectl_user_id", "") if bound else ""
        if not sectl_user_id:
            yield event.plain_result("未找到绑定的思拓创联账号信息，请重新绑定。")
            return
        image_data, image_filename = await _extract_image_base64(event)
        if image_data:
            yield event.plain_result("正在投稿（含图片），请稍候...")
            response = await self.hub_api.create_hub(
                title,
                description,
                author_id=sectl_user_id,
                author_name=sectl_user_id,
                image_data=image_data,
                image_filename=image_filename,
            )
            hub_id = (
                _extract_response_value(
                    response, "sequence_number", "document_id", "id"
                )
                or "新内容"
            )
            yield event.plain_result(f"Hub 投稿成功，编号：{hub_id}（含图片）")
        else:
            PENDING_HUB_SUBMISSIONS[user_id] = {
                "title": title,
                "description": description,
                "sectl_user_id": sectl_user_id,
                "timestamp": time.time(),
            }
            yield event.plain_result(
                "已保存标题和说明。请在60秒内发送图片来自动完成投稿，发送文字将自动取消。"
            )

    async def _try_complete_pending(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理待提交：有图片→完成，无图片→自动取消，超时60秒→取消。"""
        user_id = _get_user_id(event)
        pending = PENDING_HUB_SUBMISSIONS.pop(user_id, None)
        if not pending:
            return
        ts = pending.get("timestamp", 0)
        if time.time() - ts > 60:
            yield event.plain_result("投稿已超时（60秒），已自动取消。请重新发送：hub 投稿 [标题] | [描述]")
            return
        image_data, image_filename = await _extract_image_base64(event)
        if image_data:
            yield event.plain_result("正在投稿（含图片），请稍候...")
            response = await self.hub_api.create_hub(
                pending["title"],
                pending["description"],
                author_id=pending["sectl_user_id"],
                author_name=pending["sectl_user_id"],
                image_data=image_data,
                image_filename=image_filename,
            )
            hub_id = (
                _extract_response_value(
                    response, "sequence_number", "document_id", "id"
                )
                or "新内容"
            )
            yield event.plain_result(f"Hub 投稿成功，编号：{hub_id}（含图片）")
        else:
            yield event.plain_result("投稿已取消（未检测到图片）。")
            return

    async def _handle_hub_view(self, event: AstrMessageEvent, rest: str):
        """处理 Hub 查看（随机/最新/编号），最多返回 1 条并附带图片。"""
        parts = rest.strip().split()
        if not parts:
            async for _ in self._hub_view_random(event):
                yield _
            return
        mode = VIEW_MODE_ALIASES.get(parts[0], parts[0])
        if mode.isdigit():
            async for _ in self._hub_view_by_id(event, mode):
                yield _
            return
        if mode in ("最新", "随机"):
            if mode == "最新":
                async for _ in self._hub_view_latest(event):
                    yield _
            else:
                async for _ in self._hub_view_random(event):
                    yield _
            return
        async for _ in self._hub_view_by_id(event, mode):
            yield _

    async def _hub_view_random(self, event: AstrMessageEvent):
        yield event.plain_result("正在查询 Hub 内容，请稍候...")
        response = await self.hub_api.get_hub()
        if not response:
            yield event.plain_result("暂无 Hub 内容。")
            return
        async for _ in self._send_hub_with_image(event, response):
            yield _

    async def _hub_view_latest(self, event: AstrMessageEvent):
        yield event.plain_result("正在查询最新 Hub 内容，请稍候...")
        hubs, total = await self.hub_api.get_hubs(limit=1)
        if not hubs:
            yield event.plain_result("暂无 Hub 内容。")
            return
        async for _ in self._send_hub_with_image(event, hubs[0]):
            yield _

    async def _hub_view_by_id(self, event: AstrMessageEvent, hub_id: str):
        yield event.plain_result("正在查询 Hub 内容，请稍候...")
        response = await self.hub_api.get_hub_by_sequence(hub_id)
        if not response:
            yield event.plain_result(f"未找到编号为 {hub_id} 的 Hub 内容。")
            return
        async for _ in self._send_hub_with_image(event, response):
            yield _

    async def _handle_hub_tags(self, event: AstrMessageEvent):
        yield event.plain_result("正在查询标签列表，请稍候...")
        tags = await self.hub_api.get_tags()
        if not tags:
            yield event.plain_result("暂无可用标签。")
            return
        lines = ["📣 Hub 可用标签", ""]
        for tag in tags:
            lines.append(f"  {tag.get('name', '?')}（{tag.get('count', 0)}）")
        yield event.plain_result("\r\n".join(lines))

    async def _handle_hub_update(self, event: AstrMessageEvent, rest: str):
        hub_id, remaining = _split_first(rest)
        if not hub_id or not remaining:
            yield event.plain_result("请发送：hub 编辑 [编号] [新标题] | [新描述]")
            return
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("编辑前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        parts = remaining.split("|", 1)
        title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        yield event.plain_result("正在查询 Hub 内容，请稍候...")
        hub_doc = await self.hub_api.get_hub_by_sequence(hub_id)
        if not hub_doc or not hub_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {hub_id} 的 Hub 内容。")
            return
        yield event.plain_result("正在更新，请稍候...")
        await self.hub_api.update_hub(hub_doc["document_id"], title, description)
        yield event.plain_result(f"Hub #{hub_id} 已更新。")

    async def _handle_hub_delete(self, event: AstrMessageEvent, hub_id: str):
        hub_id = hub_id.strip()
        if not hub_id:
            yield event.plain_result("请发送：hub 删除 编号")
            return
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("删除前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        yield event.plain_result("正在查询 Hub 内容，请稍候...")
        hub_doc = await self.hub_api.get_hub_by_sequence(hub_id)
        if not hub_doc or not hub_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {hub_id} 的 Hub 内容。")
            return
        yield event.plain_result("正在删除，请稍候...")
        await self.hub_api.delete_hub(hub_doc["document_id"])
        yield event.plain_result(f"Hub #{hub_id} 已删除。")

    async def _build_hub_merge_forward(self, event: AstrMessageEvent, hubs: list[dict]):
        """构建 Hub 合并转发（多条结果时使用）。"""
        bot_uin = _get_bot_id(event)
        nodes = []
        for hub in hubs:
            text = self._format_hub_batch("", [hub], 0)
            nodes.append(Node(
                uin=bot_uin,
                name=f"Hub #{hub['id']}",
                content=[Plain(text.strip())],
            ))
        yield event.chain_result([Nodes(nodes=nodes)])

    def _format_hub_batch(self, mode: str, hubs: list[dict], total: int) -> str:
        """格式化 Hub 批量文本。"""
        if not mode:
            return "\r\n".join(
                f"📣 Hub #{hub['id']}\r\n标题：{hub['title']}\r\n"
                f"描述：{hub['description']}\r\n"
                f"发布者：{hub['author']} | {hub['created_at']}"
                for hub in hubs
            )
        lines = [f"📣 Hub 内容 {mode}（共 {total} 条）", "━━━━━━━━━━━━━━"]
        for hub in hubs:
            preview = hub["title"][:40]
            if len(hub["title"]) > 40:
                preview += "..."
            lines.append(f"#{hub['id']} {preview}")
            lines.append(f"   发布者：{hub['author']} | {hub['created_at']}")
            lines.append("")
        return "\r\n".join(lines)

    async def _handle_create(self, event: AstrMessageEvent, content: str):
        """处理投稿逻辑，写操作会先检查绑定状态。"""
        if not content:
            yield event.plain_result("请发送：回声洞 投稿 内容")
            return
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("投稿前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        bound = self.auth_state.get_bound(user_id)
        sectl_user_id = (bound or {}).get("sectl_user_id", "") if bound else ""
        if not sectl_user_id:
            yield event.plain_result("未找到绑定的思拓创联账号信息，请重新绑定。")
            return
        yield event.plain_result("正在投稿，请稍候...")
        response = await self.echo_api.create_echo(content, user_id=sectl_user_id)
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

        if mode in ("最新", "随机"):
            count = _parse_limit(parts[1:])
            if mode == "最新":
                async for _ in self._view_latest(event, count):
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
        count = min(count, MAX_BATCH_LIMIT)
        yield event.plain_result("正在随机查询回声洞，请稍候...")
        echoes, total = await self.echo_api.get_echoes(mode="random", limit=count)
        if not echoes:
            yield event.plain_result("未找到回声洞。")
            return
        if count > MERGE_FORWARD_THRESHOLD:
            async for _ in self._build_merge_forward(event, echoes):
                yield _
        else:
            yield event.plain_result(self._format_echo_batch("随机", echoes, total))

    async def _build_merge_forward(self, event: AstrMessageEvent, echoes: list[dict]):
        """将多条回声洞构建为一条合并转发消息。
        
        所有回声洞用一个 ``Nodes`` 包装，框架视为一个合并转发段。
        仅 OneBot v11 平台支持，其他平台会降级为普通文本。
        """
        bot_uin = _get_bot_id(event)
        nodes = []
        for echo in echoes:
            text = self._format_echo_batch("", [echo], 0)
            nodes.append(Node(
                uin=bot_uin,
                name=f"回声洞 #{echo['id']}",
                content=[Plain(text.strip())],
            ))
        yield event.chain_result([Nodes(nodes=nodes)])

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

    async def _view_latest(self, event: AstrMessageEvent, count: int):
        count = min(count, MAX_BATCH_LIMIT)
        yield event.plain_result("正在查询最新回声洞，请稍候...")
        echoes, total = await self.echo_api.get_echoes(mode="latest", limit=count)
        if not echoes:
            yield event.plain_result("暂无回声洞。")
            return
        if count > MERGE_FORWARD_THRESHOLD:
            async for _ in self._build_merge_forward(event, echoes):
                yield _
        else:
            yield event.plain_result(self._format_echo_batch("最新", echoes, total))

    async def _handle_my_echoes(self, event: AstrMessageEvent):
        """查询当前用户投稿的回声洞列表。"""
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("请先完成 QQ 绑定：绑定 [临时Key]")
            return
        yield event.plain_result("正在查询你的回声洞，请稍候...")
        # _ensure_bound 已缓存绑定状态，直接从缓存取 QQ 号
        bound = self.auth_state.get_bound(user_id)
        qq_number = (bound or {}).get("qq", "") if bound else ""
        if not qq_number:
            yield event.plain_result("未找到绑定的 QQ 号。")
            return
        echoes = await self.echo_api.get_my_echoes(qq_number)
        if not echoes:
            yield event.plain_result("你还没有投稿过回声洞。")
            return
        if len(echoes) > MERGE_FORWARD_THRESHOLD:
            async for _ in self._build_merge_forward(event, echoes):
                yield _
        else:
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
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("编辑前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        bound = self.auth_state.get_bound(user_id)
        sectl_user_id = (bound or {}).get("sectl_user_id", "") if bound else ""
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
            return
        yield event.plain_result("正在更新，请稍候...")
        await self.echo_api.update_echo(echo_doc["document_id"], content, author_id=sectl_user_id or None, qq_number=user_id)
        yield event.plain_result(f"回声洞 #{echo_id} 已更新。")

    async def _handle_delete(self, event: AstrMessageEvent, echo_id: str):
        echo_id = echo_id.strip()
        if not echo_id:
            yield event.plain_result("请发送：回声洞 删除 编号")
            return
        user_id = _get_user_id(event)
        if not await self._ensure_bound(event):
            yield event.plain_result("删除前请先完成 QQ 绑定：绑定 [临时Key]")
            return
        bound = self.auth_state.get_bound(user_id)
        sectl_user_id = (bound or {}).get("sectl_user_id", "") if bound else ""
        yield event.plain_result("正在查询回声洞，请稍候...")
        echo_doc = await self.echo_api.get_echo_by_sequence(echo_id)
        if not echo_doc or not echo_doc.get("document_id"):
            yield event.plain_result(f"未找到编号为 {echo_id} 的回声洞。")
            return
        yield event.plain_result("正在删除，请稍候...")
        await self.echo_api.delete_echo(echo_doc["document_id"], author_id=sectl_user_id or None, qq_number=user_id)
        yield event.plain_result(f"回声洞 #{echo_id} 已删除。")

    def _format_echo_batch(
        self, mode: str, echoes: list[dict], total: int
    ) -> str:
        if not mode:
            return "\r\n".join(
                f"📣 回声洞 #{echo['id']}\r\n{echo['content']}\r\n"
                f"发布者：{echo['author']}\r\n时间：{echo['created_at']}"
                for echo in echoes
            )
        lines = [f"📣 回声洞 {mode}（共 {total} 条）", "━━━━━━━━━━━━━━"]
        for echo in echoes:
            preview = echo["content"][:60]
            if len(echo["content"]) > 60:
                preview += "..."
            lines.append(f"#{echo['id']} {preview}")
            lines.append(f"   发布者：{echo['author']} | {echo['created_at']}")
            lines.append("")
        return "\r\n".join(lines)

    async def _handle_bind_confirm(self, event: AstrMessageEvent, key: str) -> str:
        """确认绑定 Key，并刷新本地绑定状态。绑定前先静默检测是否已绑定。"""
        qq_number = _get_user_id(event)
        bound = self.auth_state.get_bound(qq_number)
        if bound:
            qq = bound.get("qq", qq_number)
            sectl_user_id = bound.get("sectl_user_id", "")
            return f"你已经绑定过 QQ 账号 {qq}（思拓创联账号：{sectl_user_id}），无需重复绑定。"
        try:
            status = await self.binding_api.get_status(
                qq_number, token=self.config.api_token or None
            )
            if _is_bound_status(status):
                qq = str(_extract_response_value(status, "qq_number", "qq") or qq_number)
                sectl_user = str(status.get("user_id", "")) or ""
                self.auth_state.set_bound(qq_number, {"qq": qq, "sectl_user_id": sectl_user})
                return f"你已经绑定过 QQ 账号 {qq}（思拓创联账号：{sectl_user}），无需重复绑定。"
        except EchoCaveApiError as error:
            logger.warning(f"绑定前检测状态失败，继续执行确认流程：{error}")
        await self.binding_api.confirm(qq_number, key)
        status = await self.binding_api.get_status(
            qq_number, token=self.config.api_token or None
        )
        if _is_bound_status(status):
            qq = str(_extract_response_value(status, "qq_number", "qq") or qq_number)
            sectl_user = str(status.get("user_id", "")) or ""
            self.auth_state.set_bound(qq_number, {"qq": qq, "sectl_user_id": sectl_user})
            return f"QQ号 {qq} 成功绑定了思拓创联账号 {sectl_user}"
        raise EchoCaveApiError("绑定确认已提交，但服务端仍未返回已绑定状态，请稍后重试。")

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
                    ),
                    "sectl_user_id": str(status.get("user_id", "")),
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
            sectl_user = status.get("user_id", "") or ""
            self.auth_state.set_bound(user_id, {"qq": qq, "sectl_user_id": sectl_user})
            return f"QQ号 {qq} 绑定了思拓创联账号 {sectl_user or '未知'}"
        self.auth_state.clear_bound(user_id)
        return "当前QQ尚未绑定思拓创联账号"

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


def _parse_limit(tokens: list[str]) -> int:
    """解析查看指令中的数量参数，上限 MAX_BATCH_LIMIT。"""
    for token in tokens:
        if token.isdigit():
            return min(max(int(token), 1), MAX_BATCH_LIMIT)
    return 1


def _get_bot_id(event: AstrMessageEvent) -> str:
    """从事件中提取 bot 自身标识（QQ 号），用于合并转发发送者展示。"""
    self_id = getattr(event, "get_self_id", None)
    if callable(self_id):
        value = self_id()
        if value:
            return str(value)
    self_id = getattr(event, "self_id", None)
    if self_id:
        return str(self_id)
    message_obj = getattr(event, "message_obj", None)
    if message_obj:
        self_id = getattr(message_obj, "self_id", None)
        if self_id:
            return str(self_id)
    return "3057485835"


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


def _split_hub_action(command_text: str) -> tuple[str, str]:
    """拆分 hub 二级指令和剩余参数。"""
    text = command_text.removeprefix("hub").strip()
    return _split_first(text)
