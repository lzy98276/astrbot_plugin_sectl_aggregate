"""文本渲染模块：生成菜单、回声洞、Hub、设备状态等纯文本输出。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _format_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=None) + timedelta(hours=8)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


class Renderer:
    """所有文本渲染方法集中在此。"""

    def render_root_menu_text(self) -> str:
        return "\r\n".join([
            "📣 黎悠看板娘指令菜单",
            "",
            "📖 帮助",
            "  /help              查看帮助菜单",
            "",
            "🚀 功能",
            "  /回声洞 帮助        回声洞社区投稿/查看",
            "  /hub 帮助           Hub 内容中心投稿/查看",
            "  /spy               黎泽懿设备实时状态",
            "",
            "🔐 账号",
            "  /绑定 [临时Key]    完成 QQ 绑定",
            "  /解绑              解绑当前 QQ 账号",
            "  /绑定状态           查看 QQ 绑定状态",
        ])

    def render_menu_text(self) -> str:
        return "\r\n".join([
            "📣 回声洞指令菜单",
            "写操作需要先完成 QQ 绑定",
            "",
            "📝 投稿",
            "  /回声洞 投稿 [内容]          发布一条回声洞",
            "",
            "👀 查看",
            "  /回声洞 查看 随机 [数量]      随机查看（最多30条）",
            "  /回声洞 查看 [编号]          按编号查看",
            "  /回声洞 查看 最新 [数量]      查看最新（最多30条）",
            "  /回声洞 我的                 查看我的投稿",
            "",
            "✏️ 管理",
            "  /回声洞 编辑 [编号] [新内容]  编辑我的投稿",
            "  /回声洞 删除 [编号]          删除我的投稿",
        ])

    def render_hub_menu_text(self) -> str:
        return "\r\n".join([
            "📣 Hub 内容中心指令",
            "投稿需要附带图片，写操作需绑定 QQ",
            "",
            "📝 投稿",
            "  /hub 投稿 [标题] | [描述]    发布 Hub（带图片）",
            "",
            "👀 查看",
            "  /hub 查看 [编号]            按编号查看（带图片）",
            "  /hub 查看 随机              随机查看（带图片）",
            "  /hub 查看 最新              最新查看（带图片）",
            "  /hub 标签                  查看可用标签",
            "",
            "✏️ 管理",
            "  /hub 编辑 [编号] [新标题] | [新描述]  编辑我的内容",
            "  /hub 删除 [编号]                     删除我的内容",
        ])

    def render_echo_text(self, echo_data: dict[str, Any]) -> str:
        normalized = _normalize_echo_data(echo_data)
        return "\r\n".join([
            f"📣 回声洞 #{normalized['id']}",
            f"{normalized['content']}",
            f"发布者：{normalized['author']}",
            f"时间：{normalized['created_at']}",
        ])

    def render_hub_text(self, hub_data: dict[str, Any]) -> str:
        created_at = hub_data.get("created_at", "")
        time_str = _format_time(created_at) if created_at else ""
        lines = [f"📣 Hub #{hub_data.get('id', '')}"]
        lines.append(f"标题：{hub_data.get('title', '')}")
        lines.append(f"描述：{hub_data.get('description', '')}")
        tags = hub_data.get("tags", [])
        if tags:
            lines.append(f"标签：{' '.join(tags)}")
        lines.append(f"发布者：{hub_data.get('author', '匿名')}")
        if time_str:
            lines.append(time_str)
        lines.append(f"浏览量：{hub_data.get('views', 0)}")
        return "\r\n".join(lines)

    def render_device_status_text(self, data: dict[str, Any]) -> str:
        from api.device_status import format_device_status
        return format_device_status(data)


def _normalize_echo_data(echo_data: dict[str, Any]) -> dict[str, str]:
    data = echo_data.get("data", echo_data)
    if isinstance(data, dict) and "documents" in data and data["documents"]:
        data = data["documents"][0]
    if isinstance(data, dict) and "document" in data and isinstance(data["document"], dict):
        data = data["document"]
    if isinstance(data, dict) and "echo" in data and isinstance(data["echo"], dict):
        data = data["echo"]
    if not isinstance(data, dict):
        data = {"content": str(data)}
    return {
        "id": str(
            data.get("sequence_number")
            or data.get("id")
            or data.get("document_id")
            or data.get("echo_id")
            or "随机"
        ),
        "content": str(data.get("content") or data.get("text") or "暂无内容"),
        "author": str(
            data.get("author_name")
            or data.get("author")
            or data.get("author_id")
            or data.get("user_id")
            or "匿名"
        ),
        "created_at": str(data.get("created_at") or data.get("time") or "未知"),
    }
