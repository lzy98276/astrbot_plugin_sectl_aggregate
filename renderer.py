"""HTML 模板渲染和文转图辅助模块。"""

from __future__ import annotations

import html
from pathlib import Path
from string import Template
from typing import Any


class HtmlTemplateRenderer:
    """使用轻量模板替换生成 HTML，保留后续接入截图渲染的扩展点。"""

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir

    def render_menu(self) -> str:
        """渲染回声洞帮助菜单 HTML。"""
        commands = [
            {"name": "help", "desc": "查看回声洞帮助菜单"},
            {
                "name": "回声洞 投稿 内容",
                "desc": "投稿一条新的回声洞，需要先完成 QQ 绑定",
            },
            {"name": "回声洞 查看 [编号]", "desc": "随机查看或按编号查看回声洞"},
            {"name": "回声洞 我的", "desc": "查看自己投稿的回声洞列表"},
            {"name": "回声洞 编辑 编号 新内容", "desc": "编辑自己发布的回声洞"},
            {"name": "回声洞 删除 编号", "desc": "删除自己发布的回声洞"},
            {"name": "绑定 QQ号", "desc": "申请 QQ 绑定 Key"},
            {"name": "绑定状态", "desc": "查看当前账号 QQ 绑定状态"},
        ]
        items = "".join(
            f"<li><strong>{html.escape(item['name'])}</strong><span>{html.escape(item['desc'])}</span></li>"
            for item in commands
        )
        return self._render("menu.html", {"commands": items})

    def render_echo(self, echo_data: dict[str, Any]) -> str:
        """渲染单条回声洞展示 HTML。"""
        normalized = _normalize_echo_data(echo_data)
        return self._render(
            "echo_display.html",
            {
                "echo_id": html.escape(normalized["id"]),
                "content": html.escape(normalized["content"]).replace("\n", "<br>"),
                "author": html.escape(normalized["author"]),
                "created_at": html.escape(normalized["created_at"]),
            },
        )

    def render_menu_text(self) -> str:
        """生成纯文本菜单，作为图片能力不可用时的降级输出。"""
        return "\n".join(
            [
                "📣 回声洞指令菜单",
                "help：查看帮助菜单",
                "回声洞 投稿 内容：投稿回声洞",
                "回声洞 查看 [编号]：随机或按编号查看",
                "回声洞 我的：查看自己投稿的回声洞",
                "回声洞 编辑 编号 新内容：编辑回声洞",
                "回声洞 删除 编号：删除回声洞",
                "绑定 QQ号：申请 QQ 绑定 Key",
                "绑定状态：查看绑定状态",
            ]
        )

    def render_echo_text(self, echo_data: dict[str, Any]) -> str:
        """生成纯文本回声洞内容，保证所有平台都能展示。"""
        normalized = _normalize_echo_data(echo_data)
        return "\n".join(
            [
                f"📣 回声洞 #{normalized['id']}",
                normalized["content"],
                f"发布者：{normalized['author']}",
                f"时间：{normalized['created_at']}",
            ]
        )

    def _render(self, template_name: str, values: dict[str, str]) -> str:
        """读取模板并替换变量。"""
        template = Template(
            (self.template_dir / template_name).read_text(encoding="utf-8")
        )
        return template.safe_substitute(values)


def _normalize_echo_data(echo_data: dict[str, Any]) -> dict[str, str]:
    """兼容不同 API 响应结构，提取展示所需字段。"""
    data = echo_data.get("data", echo_data)
    if isinstance(data, dict) and "documents" in data and data["documents"]:
        data = data["documents"][0]
    if isinstance(data, dict) and "document" in data and isinstance(
        data["document"], dict
    ):
        data = data["document"]
    if isinstance(data, dict) and "echo" in data and isinstance(data["echo"], dict):
        data = data["echo"]
    if not isinstance(data, dict):
        data = {"content": str(data)}
    return {
        "id": str(
            data.get("sequence_number")
            or data.get("document_id")
            or data.get("id")
            or data.get("echo_id")
            or "随机"
        ),
        "content": str(data.get("content") or data.get("text") or "暂无内容"),
        "author": str(
            data.get("author") or data.get("author_id") or data.get("user_id") or "匿名"
        ),
        "created_at": str(data.get("created_at") or data.get("time") or "未知"),
    }
