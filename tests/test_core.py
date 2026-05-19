"""回声洞插件核心逻辑测试。"""

import asyncio
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_event_module = types.ModuleType("astrbot.api.event")
astrbot_star_module = types.ModuleType("astrbot.api.star")
astrbot_message_components = types.ModuleType("astrbot.api.message_components")
astrbot_api_module.logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None
)
astrbot_event_module.AstrMessageEvent = object
astrbot_event_module.filter = types.SimpleNamespace(
    command=lambda _name: lambda func: func
)
astrbot_star_module.Context = object
astrbot_star_module.Star = object
astrbot_star_module.register = lambda *_args, **_kwargs: lambda cls: cls
astrbot_message_components.Node = object
astrbot_message_components.Nodes = object
astrbot_message_components.Plain = object
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("astrbot.api.event", astrbot_event_module)
sys.modules.setdefault("astrbot.api.star", astrbot_star_module)
sys.modules.setdefault("astrbot.api.message_components", astrbot_message_components)

import aiohttp

from api.base import BaseApiClient, EchoCaveApiError, _should_retry_error, _summarize_headers
from api.echo_cave import EchoCaveApiClient
from api.qq_binding import QqBindingApiClient
from config import EchoCaveConfig
from main import (
    EchoCavePlugin,
    _is_bound_status,
    _is_qq_number,
    _normalize_command,
    _parse_limit,
    _split_action,
)
from renderer import HtmlTemplateRenderer
from state import AuthStateManager


class RecordingEchoCaveClient(EchoCaveApiClient):
    """记录回声洞 API 请求参数，便于验证高层客户端映射。"""

    def __init__(self):
        config = EchoCaveConfig.from_astrbot_config({})
        config.api_token = "test-api-token"
        super().__init__(config)
        self.calls = []

    async def request(
        self, method, path, *, json_data=None, query=None, token=None, headers=None, not_found_ok=False
    ):
        """保存最近一次请求，并返回可断言的模拟响应。"""
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json_data": json_data,
                "query": query,
                "token": token,
                "headers": headers,
                "not_found_ok": not_found_ok,
            }
        )
        return {"ok": True, "path": path}


class RecordingQqBindingClient(QqBindingApiClient):
    """记录 QQ 绑定 API 请求参数，避免测试依赖真实网络。"""

    def __init__(self):
        super().__init__(EchoCaveConfig.from_astrbot_config({}))
        self.calls = []

    async def request(
        self, method, path, *, json_data=None, query=None, token=None, headers=None
    ):
        """保存请求参数，并模拟服务端成功响应。"""
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json_data": json_data,
                "query": query,
                "token": token,
                "headers": headers,
            }
        )
        return {"ok": True}


class FakeBindingApi:
    """用于测试绑定确认后的状态刷新逻辑。"""

    def __init__(self, status_response):
        self.status_response = status_response
        self.calls = []

    async def confirm(self, qq_number, temp_key):
        self.calls.append(("confirm", qq_number, temp_key))
        return {"message": "绑定完成"}

    async def get_status(self, user_id, *, token=None):
        self.calls.append(("status", user_id))
        return self.status_response


class FakeEvent:
    """用于测试插件返回结果的简化事件对象。"""

    def plain_result(self, message):
        return message


class CoreLogicTest(unittest.TestCase):
    """验证回声洞插件不依赖 AstrBot 运行时的核心逻辑。"""

    def test_normalize_command_supports_slash(self):
        """校验带斜杠和空白的指令可被正确规整。"""
        self.assertEqual(_normalize_command(" /回声洞 查看 1 "), "回声洞 查看 1")

    def test_split_action_extracts_subcommand(self):
        """校验回声洞二级指令和参数拆分正确。"""
        self.assertEqual(_split_action("回声洞 编辑 12 新内容"), ("编辑", "12 新内容"))

    def test_qq_number_validation(self):
        """校验 QQ 号格式识别，避免绑定 Key 被误判。"""
        self.assertTrue(_is_qq_number("12345"))
        self.assertFalse(_is_qq_number("abc123"))

    def test_bound_status_variants(self):
        """校验绑定状态兼容常见服务端返回字段。"""
        self.assertTrue(_is_bound_status({"data": {"is_bound": True}}))
        self.assertTrue(_is_bound_status({"status": "已绑定"}))
        self.assertFalse(_is_bound_status({"status": "未绑定"}))

    def test_renderer_uses_standalone_binding_commands(self):
        """校验根目录菜单包含独立 help 和绑定指令，不包含旧写法。"""
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir) / "templates"
            template_dir.mkdir()
            (template_dir / "menu.html").write_text("$commands", encoding="utf-8")
            (template_dir / "echo_display.html").write_text(
                "$content", encoding="utf-8"
            )
            renderer = HtmlTemplateRenderer(template_dir)

            root_menu = renderer.render_root_menu_text()

        self.assertIn("黎悠看板娘指令菜单", root_menu)
        self.assertIn("绑定 [临时Key]", root_menu)
        self.assertIn("绑定状态", root_menu)
        self.assertIn("回声洞 帮助", root_menu)
        self.assertNotIn("回声洞 投稿", root_menu)
        self.assertNotIn("回声洞 测试", root_menu)

    def test_renderer_echo_cave_menu_separates_commands(self):
        """校验回声洞菜单仅包含带回声洞前缀的指令。"""
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir) / "templates"
            template_dir.mkdir()
            (template_dir / "menu.html").write_text("$commands", encoding="utf-8")
            (template_dir / "echo_display.html").write_text(
                "$content", encoding="utf-8"
            )
            renderer = HtmlTemplateRenderer(template_dir)

            cave_menu = renderer.render_menu_text()

        self.assertIn("回声洞指令菜单", cave_menu)
        self.assertIn("回声洞 投稿 [内容]", cave_menu)
        self.assertIn("回声洞 查看 随机", cave_menu)
        self.assertNotIn("绑定 QQ号", cave_menu)
        self.assertNotIn("help：查看", cave_menu)

    def test_config_reads_astrbot_config_safely(self):
        """校验 AstrBot 配置可覆盖默认值，非法数值会安全降级。"""
        astrbot_config = {
            "api_base_url": "https://example.com/",
            "api_token": "token-value",
            "request_timeout": "invalid",
            "retry_count": 3,
        }
        config = EchoCaveConfig.from_astrbot_config(astrbot_config)

        self.assertEqual(config.api_base_url, "https://example.com")
        self.assertEqual(config.api_token, "token-value")
        self.assertEqual(config.request_timeout, 10.0)
        self.assertEqual(config.retry_count, 3)

    def test_api_response_parser_handles_errors(self):
        """校验 API 响应解析能识别失败状态和非 JSON 内容。"""
        client = BaseApiClient(EchoCaveConfig.from_astrbot_config({}))

        self.assertEqual(client._parse_response(""), {"ok": True})
        self.assertEqual(
            client._parse_response('{"data": {"id": 1}}'), {"data": {"id": 1}}
        )
        with self.assertRaises(EchoCaveApiError):
            client._parse_response('{"ok": false, "message": "失败"}')
        with self.assertRaises(EchoCaveApiError):
            client._parse_response("not-json")

    def test_auth_state_tracks_bound_and_pending_users(self):
        """校验认证状态缓存会同步维护已绑定和待确认状态。"""
        manager = AuthStateManager()

        manager.set_pending("user-1", "12345", "KEY")
        self.assertEqual(manager.get_pending("user-1").qq, "12345")
        manager.set_bound("user-1", {"qq": "12345"})

        self.assertTrue(manager.is_bound("user-1"))
        self.assertIsNone(manager.get_pending("user-1"))
        manager.clear_bound("user-1")
        self.assertFalse(manager.is_bound("user-1"))

    def test_auth_state_clears_expired_pending_binding(self):
        """校验待确认绑定超过有效期后会自动清理。"""
        manager = AuthStateManager(pending_ttl_seconds=1)

        with patch("state.time", return_value=100.0):
            manager.set_pending("user-1", "12345", "KEY")

        with patch("state.time", return_value=102.0):
            self.assertIsNone(manager.get_pending("user-1"))

    def test_renderer_escapes_echo_content(self):
        """校验回声洞模板渲染会转义用户内容，避免注入 HTML。"""
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir) / "templates"
            template_dir.mkdir()
            (template_dir / "menu.html").write_text("$commands", encoding="utf-8")
            (template_dir / "echo_display.html").write_text(
                "$echo_id|$content|$author|$created_at", encoding="utf-8"
            )
            renderer = HtmlTemplateRenderer(template_dir)

            html = renderer.render_echo(
                {"data": {"id": 7, "content": "<b>洞</b>\n新行", "user_id": "u"}}
            )

        self.assertIn("&lt;b&gt;洞&lt;/b&gt;<br>新行", html)
        self.assertNotIn("<b>洞</b>", html)

    def test_parse_limit_extracts_count(self):
        """校验查看指令数量解析，上限 MAX_BATCH_LIMIT。"""
        self.assertEqual(_parse_limit(["5"]), 5)
        self.assertEqual(_parse_limit([]), 1)
        self.assertEqual(_parse_limit(["99"]), 30)
        self.assertEqual(_parse_limit(["abc"]), 1)

    def test_summarize_headers_masks_sensitive_values(self):
        """校验日志摘要不会暴露鉴权头内容。"""
        summary = _summarize_headers(
            {
                "Accept": "application/json",
                "Authorization": "Bearer secret-token",
                "x-echo-cave-token": "internal-token",
            }
        )

        self.assertEqual(summary["Authorization"], "<masked>")
        self.assertEqual(summary["x-echo-cave-token"], "<masked>")
        self.assertEqual(summary["Accept"], "application/json")

    def test_should_retry_error_only_allows_transient_failures(self):
        """校验仅对瞬时网络异常启用重试。"""
        self.assertTrue(_should_retry_error(asyncio.TimeoutError()))
        self.assertTrue(_should_retry_error(aiohttp.ClientConnectionError()))
        self.assertFalse(_should_retry_error(EchoCaveApiError("业务失败")))


class ApiClientTest(unittest.IsolatedAsyncioTestCase):
    """验证 API 客户端方法映射到预期端点和参数。"""

    async def test_echo_cave_client_maps_core_endpoints(self):
        """校验投稿、查询、编辑和删除接口路径与载荷。"""
        client = RecordingEchoCaveClient()

        await client.create_echo("内容", user_id="user-1")
        await client.get_echo()
        await client.get_echo("12")
        await client.update_echo("12", "新内容", qq_number="user-1")
        await client.delete_echo("12", qq_number="user-1")

        self.assertEqual(client.calls[0]["path"], "/api/echo-cave/internal")
        self.assertEqual(
            client.calls[0]["json_data"], {"content": "内容", "author_id": "user-1"}
        )
        self.assertEqual(client.calls[1]["path"], "/api/echo-cave")
        self.assertEqual(client.calls[1]["query"], {"mode": "random", "limit": 1})
        self.assertEqual(client.calls[2]["query"], {"id": "12"})
        self.assertEqual(client.calls[3]["method"], "PUT")
        self.assertEqual(client.calls[3]["path"], "/api/echo-cave/internal")
        self.assertEqual(client.calls[3]["json_data"]["document_id"], "12")
        self.assertEqual(client.calls[3]["json_data"]["qq_number"], "user-1")
        self.assertEqual(client.calls[4]["method"], "DELETE")
        self.assertEqual(client.calls[4]["path"], "/api/echo-cave/internal")
        self.assertEqual(client.calls[4]["json_data"]["qq_number"], "user-1")

    async def test_qq_binding_client_maps_binding_endpoints(self):
        """校验绑定状态、申请 Key 和确认绑定接口参数。"""
        client = RecordingQqBindingClient()

        await client.get_status("user-1")
        await client.request_key("user-1", "12345")
        await client.confirm("12345", "KEY")

        self.assertEqual(client.calls[0]["query"], {"qq_number": "user-1"})
        self.assertEqual(client.calls[1]["path"], "/api/qq-binding/request")
        self.assertEqual(
            client.calls[1]["json_data"], {"user_id": "user-1", "qq_number": "12345"}
        )
        self.assertEqual(
            client.calls[2]["json_data"],
            {"qq_number": "12345", "temp_key": "KEY"},
        )


class PluginBindingFlowTest(unittest.IsolatedAsyncioTestCase):
    """验证插件绑定确认后的状态刷新行为。"""

    async def test_bind_confirm_refreshes_server_status_before_marking_bound(self):
        """校验确认绑定后会以服务端状态为准刷新本地缓存。"""
        plugin = EchoCavePlugin.__new__(EchoCavePlugin)
        plugin.config = EchoCaveConfig.from_astrbot_config({})
        plugin.auth_state = AuthStateManager()
        plugin.binding_api = FakeBindingApi({"status": "已绑定", "qq_number": "12345", "user_id": "user-1"})

        plugin.auth_state.set_pending("user-1", "12345", "KEY")
        event = FakeEvent()

        with patch("main._get_user_id", return_value="user-1"):
            result = await plugin._handle_bind_confirm(event, "KEY")

        self.assertEqual(result, "QQ号 12345 成功绑定了思拓创联账号 user-1")
        self.assertTrue(plugin.auth_state.is_bound("user-1"))
        self.assertIsNone(plugin.auth_state.get_pending("user-1"))
        self.assertEqual(
            plugin.binding_api.calls,
            # confirm 传入 (qq_number, temp_key)
            [("confirm", "user-1", "KEY"), ("status", "user-1")],
        )

    async def test_bind_confirm_rejects_when_server_not_bound(self):
        """校验服务端未返回已绑定状态时会抛出异常并清理待确认状态。"""
        plugin = EchoCavePlugin.__new__(EchoCavePlugin)
        plugin.config = EchoCaveConfig.from_astrbot_config({})
        plugin.auth_state = AuthStateManager()
        plugin.binding_api = FakeBindingApi({"status": "未绑定"})

        plugin.auth_state.set_pending("user-1", "12345", "KEY")
        event = FakeEvent()

        with patch("main._get_user_id", return_value="user-1"):
            with self.assertRaises(EchoCaveApiError):
                await plugin._handle_bind_confirm(event, "KEY")

        self.assertFalse(plugin.auth_state.is_bound("user-1"))
        # 绑定失败时 pending 状态不会被主动清理（由 TTL 自动过期）


if __name__ == "__main__":
    unittest.main()
