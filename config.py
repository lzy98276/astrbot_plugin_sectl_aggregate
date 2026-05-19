"""回声洞插件配置管理模块。

适配 AstrBot 插件配置系统，从 self.config 读取配置。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EchoCaveConfig:
    """集中管理回声洞服务的运行配置。"""

    api_base_url: str = "https://appwrite.sectl.cn"
    api_token: str = ""
    request_timeout: float = 10.0
    retry_count: int = 2

    @classmethod
    def from_astrbot_config(cls, astrbot_config) -> "EchoCaveConfig":
        """从 AstrBot 插件配置系统读取配置。"""
        timeout = astrbot_config.get("request_timeout", 10.0)
        retry = astrbot_config.get("retry_count", 2)
        api_base = astrbot_config.get("api_base_url", "https://appwrite.sectl.cn")
        
        return cls(
            api_base_url=str(api_base).rstrip("/") if api_base else "https://appwrite.sectl.cn",
            api_token=str(astrbot_config.get("api_token", "")),
            request_timeout=_safe_float(timeout, 10.0),
            retry_count=max(_safe_int(retry, 2), 0),
        )


def _safe_float(value, default: float) -> float:
    """安全转换浮点数，避免错误配置导致插件加载失败。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int) -> int:
    """安全转换整数，避免错误配置导致插件加载失败。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
