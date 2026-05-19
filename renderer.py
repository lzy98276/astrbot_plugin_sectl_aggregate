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

    def render_root_menu(self) -> str:
        """渲染根目录帮助菜单 HTML。"""
        commands = [
            {"name": "/help", "desc": "查看帮助菜单"},
            {"name": "/回声洞 帮助", "desc": "查看回声洞专属帮助菜单"},
            {"name": "/hub 帮助", "desc": "查看 Hub 内容中心帮助菜单"},
            {"name": "/绑定 [临时Key]", "desc": "使用 Key 完成 QQ 绑定"},
            {"name": "/解绑", "desc": "解绑当前 QQ 账号"},
            {"name": "/绑定状态", "desc": "查看当前账号 QQ 绑定状态"},
        ]
        items = "".join(
            f"<li><strong>{html.escape(item['name'])}</strong><span>{html.escape(item['desc'])}</span></li>"
            for item in commands
        )
        return self._render("menu.html", {"commands": items})

    def render_menu(self) -> str:
        """渲染回声洞帮助菜单 HTML。"""
        commands = [
            {
                "name": "/回声洞 投稿 [内容]",
                "desc": "投稿一条新的回声洞，需要先完成 QQ 绑定",
            },
            {"name": "/回声洞 查看 随机 [数量]", "desc": "随机查看多条回声洞（最多30条）"},
            {"name": "/回声洞 查看 [编号]", "desc": "按编号查看单条回声洞"},
            {
                "name": "/回声洞 查看 最新 [数量]",
                "desc": "查看最新 N 条（最多30条）",
            },
            {"name": "/回声洞 我的", "desc": "查看自己投稿的回声洞列表"},
            {"name": "/回声洞 编辑 [编号] [新内容]", "desc": "编辑自己发布的回声洞"},
            {"name": "/回声洞 删除 [编号]", "desc": "删除自己发布的回声洞"},
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

    def render_root_menu_text(self) -> str:
        """生成根目录纯文本菜单"""
        return "\r\n".join(
            [
                "📣 黎悠看板娘指令菜单",
                "/help：查看帮助菜单",
                "/回声洞 帮助：查看回声洞帮助菜单",
                "/hub 帮助：查看 Hub 内容中心帮助菜单",
                "/绑定 [临时Key]：使用 Key 完成 QQ 绑定",
                "/解绑：解绑当前 QQ 账号",
                "/绑定状态：查看绑定状态",
            ]
        )

    def render_menu_text(self) -> str:
        """生成回声洞纯文本菜单。"""
        return "\r\n".join(
            [
                "📣 回声洞指令列表",
                "/回声洞 投稿 [内容]：投稿回声洞（需绑定 QQ）",
                "/回声洞 查看 随机 [数量]：随机查看多条",
                "/回声洞 查看 [编号]：按编号查看",
                "/回声洞 查看 最新 [数量]：查看最新",
                "/回声洞 我的：查看自己投稿的列表",
                "/回声洞 编辑 [编号] [新内容]：编辑自己的回声洞",
                "/回声洞 删除 [编号]：删除自己的回声洞",
            ]
        )

    def render_hub_menu(self) -> str:
        """渲染 Hub 内容中心帮助菜单 HTML。"""
        commands = [
            {
                "name": "/hub 投稿 [标题] | [描述]",
                "desc": "投稿 Hub（带图则一段式提交，无图则保存等待后续 hub+图片），需先绑定 QQ",
            },
            {"name": "/hub 查看 [编号]", "desc": "按编号查看单条 Hub 内容（附带图片）"},
            {"name": "/hub 查看 随机", "desc": "随机查看一条 Hub 内容（附带图片）"},
            {"name": "/hub 查看 最新", "desc": "查看最新一条 Hub 内容（附带图片）"},
            {"name": "/hub 标签", "desc": "查看可用标签列表"},
            {"name": "/hub 编辑 [编号] [新标题] | [新描述]", "desc": "编辑自己的 Hub 内容"},
            {"name": "/hub 删除 [编号]", "desc": "删除自己的 Hub 内容"},
            {"name": "/hub 投稿取消", "desc": "取消待提交的 Hub 投稿"},
        ]
        items = "".join(
            f"<li><strong>{html.escape(item['name'])}</strong><span>{html.escape(item['desc'])}</span></li>"
            for item in commands
        )
        return self._render("menu.html", {"commands": items})

    def render_hub_menu_text(self) -> str:
        """生成 Hub 纯文本菜单。"""
        return "\r\n".join(
            [
                "📣 Hub 内容中心指令列表",
                "/hub 投稿 [标题] | [描述]：投稿 Hub（带图一段式/无图二段式），需绑定 QQ",
                "/hub 投稿取消：取消待提交的投稿",
                "/hub 查看 [编号]：按编号查看（附带图片）",
                "/hub 查看 随机：随机查看一条（附带图片）",
                "/hub 查看 最新：查看最新一条（附带图片）",
                "/hub 标签：查看可用标签",
                "/hub 编辑 [编号] [新标题] | [新描述]：编辑自己的 Hub",
                "/hub 删除 [编号]：删除自己的 Hub",
            ]
        )

    def render_hub(self, hub_data: dict[str, Any]) -> str:
        """渲染单条 Hub 内容展示 HTML。"""
        tags_html = "".join(
            f"<span class=\"tag-item\">{html.escape(t)}</span>"
            for t in hub_data.get("tags", [])
        )
        return self._render(
            "hub_display.html",
            {
                "hub_id": html.escape(hub_data.get("id", "")),
                "title": html.escape(hub_data.get("title", "")),
                "description": html.escape(hub_data.get("description", "")).replace("\n", "<br>"),
                "author": html.escape(hub_data.get("author", "匿名")),
                "created_at": html.escape(hub_data.get("created_at", "")),
                "views": str(hub_data.get("views", 0)),
                "tags_html": tags_html,
            },
        )

    def render_hub_text(self, hub_data: dict[str, Any]) -> str:
        """生成单条 Hub 纯文本展示。"""
        lines = [f"📣 Hub #{hub_data.get('id', '')}"]
        lines.append(f"标题：{hub_data.get('title', '')}")
        lines.append(f"描述：{hub_data.get('description', '')}")
        tags = hub_data.get("tags", [])
        if tags:
            lines.append(f"标签：{' '.join(tags)}")
        lines.append(f"发布者：{hub_data.get('author', '匿名')} | {hub_data.get('created_at', '')}")
        lines.append(f"👁 {hub_data.get('views', 0)}")
        return "\r\n".join(lines)

    def render_menu_text(self) -> str:
        """生成回声洞纯文本菜单，作为图片能力不可用时的降级输出。"""
        return "\r\n".join(
            [
                "📣 回声洞指令菜单",
                "回声洞 投稿 [内容]：投稿回声洞",
                "回声洞 查看 [编号]：按编号查看单条",
                "回声洞 查看 随机 [数量]：随机查看多条（最多30）",
                "回声洞 查看 最新 [数量]：查看最新N条（最多30）",
                "回声洞 我的：查看自己投稿的回声洞",
                "回声洞 编辑 [编号] [新内容]：编辑回声洞",
                "回声洞 删除 [编号]：删除回声洞",
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
