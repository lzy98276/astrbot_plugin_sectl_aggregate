"""回声洞插件配置管理模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class EchoCaveConfig:
    """集中管理回声洞服务的运行配置。"""

    api_base_url: str = "https://appwrite.sectl.cn"
    api_token: str = ""
    internal_token: str = ""
    request_timeout: float = 10.0
    retry_count: int = 2

    @classmethod
    def from_env(cls) -> "EchoCaveConfig":
        """从环境变量读取配置，方便不同部署环境覆盖默认值。"""
        timeout_text = os.getenv("ECHO_CAVE_TIMEOUT", "10")
        retry_text = os.getenv("ECHO_CAVE_RETRY_COUNT", "2")
        return cls(
            api_base_url=os.getenv(
                "ECHO_CAVE_API_BASE_URL", "https://appwrite.sectl.cn"
            ).rstrip("/"),
            api_token=os.getenv("ECHO_CAVE_API_TOKEN", ""),
            internal_token=os.getenv("ECHO_CAVE_INTERNAL_TOKEN", ""),
            request_timeout=_safe_float(timeout_text, 10.0),
            retry_count=max(_safe_int(retry_text, 2), 0),
        )


def _safe_float(value: str, default: float) -> float:
    """安全转换浮点数，避免错误配置导致插件加载失败。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: str, default: int) -> int:
    """安全转换整数，避免错误配置导致插件加载失败。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
