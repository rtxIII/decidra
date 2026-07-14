"""把 Decidra 的 MCP 服务器幂等注册到 OpenHarness settings.json。

在终端运行时构建前调用，使 openharness 通过 stdio 以子进程方式连接各服务器：
- ``futu``     -> ``python -m decidra.mcp_server``（富途行情/交易，需 OpenD）
- ``yfinance`` -> ``python -m decidra.mcp_server.yfinance_mcp``（雅虎财经，免费无 key）
- ``czsc``     -> ``python -m decidra.mcp_server.czsc_server``（缠论信号分析，免费无 key）
- ``strategy`` -> ``python -m decidra.mcp_server.strategy_server``（策略告警读取与研判写回）

仅在对应 ``mcp_servers.<name>`` 缺失或过期时写入，保留用户其它设置。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..utils.global_vars import (
    DECIDRA_PATH as DECIDRA_HOME,
    PATH_OPENHARNESS_SETTINGS as SETTINGS_PATH,
)

# 项目根（decidra 包的父目录），供子进程 PYTHONPATH 导入 decidra。
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RegisterResult:
    """注册结果。

    Attributes:
        changed: 是否写入了变更。
        registered: 本次涉及的 server 名列表。
        settings_path: settings.json 路径。
    """

    changed: bool
    registered: list[str]
    settings_path: Path


def _stdio_config(module_args: list[str]) -> dict:
    """构造一个 stdio server 配置。

    Args:
        module_args: ``-m`` 之后的模块与参数，如 ["decidra.mcp_server"]。
    """
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", *module_args],
        "env": {"PYTHONPATH": str(PROJECT_ROOT)},
    }


def _desired_servers() -> dict[str, dict]:
    """返回 Decidra 各 MCP server 的期望配置。"""
    return {
        "futu": _stdio_config(["decidra.mcp_server"]),
        "yfinance": _stdio_config(["decidra.mcp_server.yfinance_mcp"]),
        "czsc": _stdio_config(["decidra.mcp_server.czsc_server"]),
        "strategy": _stdio_config(["decidra.mcp_server.strategy_server"]),
    }


def _load_settings() -> dict:
    """读取现有 settings.json（不存在或损坏时返回空字典）。"""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_servers(desired: dict[str, dict]) -> RegisterResult:
    """把期望的 server 配置幂等合并进 settings.json 的 mcp_servers。"""
    settings = _load_settings()
    servers = settings.get("mcp_servers")
    if not isinstance(servers, dict):
        servers = {}

    changed = False
    for name, config in desired.items():
        if servers.get(name) != config:
            servers[name] = config
            changed = True

    if not changed:
        return RegisterResult(changed=False, registered=list(desired), settings_path=SETTINGS_PATH)

    settings["mcp_servers"] = servers
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass
    return RegisterResult(changed=True, registered=list(desired), settings_path=SETTINGS_PATH)


def register_mcp_servers() -> RegisterResult:
    """把 Decidra 全部 MCP server（futu + yfinance + czsc）幂等注册到 settings.json。"""
    return _write_servers(_desired_servers())


def register_futu_mcp_server() -> RegisterResult:
    """仅注册富途 MCP server（向后兼容入口）。"""
    return _write_servers({"futu": _stdio_config(["decidra.mcp_server"])})
