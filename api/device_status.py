"""设备状态监控 API 客户端。

从 https://api.aionflux.cn/api/status 获取电脑/手机/平板在线状态。
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger("astrbot")

DEVICE_STATUS_API_URL = "https://api.aionflux.cn/api/status"

DEVICE_LABELS: dict[str, str] = {
    "computer": "电脑",
    "phone": "手机",
    "tablet": "平板",
}


class DeviceStatusError(RuntimeError):
    """表示设备状态 API 调用失败。"""


async def fetch_device_status(timeout: float = 10.0) -> dict[str, Any]:
    """从远端 API 获取三设备状态，返回原始 JSON 字典。

    Returns:
        {"computer": {...}, "phone": {...}, "tablet": {...}}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                DEVICE_STATUS_API_URL,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise DeviceStatusError(
                        f"设备状态 API 返回 HTTP {resp.status}: {text[:200]}"
                    )
                return await resp.json()
    except DeviceStatusError:
        raise
    except Exception as exc:
        raise DeviceStatusError(f"请求设备状态失败：{exc}") from exc


def format_device_status(data: dict[str, Any]) -> str:
    if not data or not isinstance(data, dict):
        return "暂时无法获取设备状态数据。"

    DEVICE_ICONS = {"computer": "🖥️", "phone": "📱", "tablet": "📟"}
    lines = ["📡 黎泽懿的设备状态", ""]

    for device_key in ("computer", "phone", "tablet"):
        device = data.get(device_key, {})
        if not isinstance(device, dict):
            continue

        label = DEVICE_LABELS.get(device_key, device_key)
        icon = DEVICE_ICONS.get(device_key, "💻")
        online = device.get("online", False)
        status_icon = "🟢" if online else "🔴"
        status_text = "在线" if online else "离线"

        lines.append(f"{icon} {status_icon} {label} ({status_text})")

        if online:
            app = device.get("app", "") or ""
            if app:
                lines.append(f"  应用     {app}")
            conn_type = device.get("connectionType", "") or ""
            if conn_type:
                lines.append(f"  连接     {conn_type}")

        battery = device.get("battery")
        if battery is not None:
            charging = device.get("charging", False)
            battery_text = f"{battery}%"
            if charging:
                battery_text += " 🔌 充电中"
            lines.append(f"  电量     {battery_text}")

        network = device.get("network", "") or ""
        if network:
            lines.append(f"  网络     {network}")

        last_update = device.get("lastUpdate", "") or ""
        if last_update:
            lines.append(f"  上报     {_format_time_short(last_update)}")

        lines.append("")

    lines.append("数据来源：aionflux.cn")
    return "\r\n".join(lines).strip()


def _format_time_short(iso_str: str) -> str:
    from datetime import datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=None) + timedelta(hours=8)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso_str
