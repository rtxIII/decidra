"""把富途 MCP 服务器幂等注册到 OpenHarness settings.json。

在终端运行时构建前调用，使 openharness 通过 stdio 以子进程方式连接
``python -m decidra.mcp_server``。仅在 ``mcp_servers.futu`` 缺失或过期时写入，保留
用户其它设置。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

DECIDRA_HOME: Path = Path.home() / ".decidra"
SETTINGS_PATH: Path = DECIDRA_HOME / "openharness" / "settings.json"

# 项目根（decidra 包的父目录），供子进程 PYTHONPATH 导入 decidra。
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

SERVER_NAME = "futu"


@dataclass(frozen=True)
class RegisterResult:
    """注册结果。

    Attributes:
        changed: 是否写入了变更。
        settings_path: settings.json 路径。
    """

    changed: bool
    settings_path: Path


def _desired_config() -> dict:
    """返回富途 MCP server 的期望 stdio 配置。"""
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "decidra.mcp_server"],
        "env": {"PYTHONPATH": str(PROJECT_ROOT)},
    }


def register_futu_mcp_server() -> RegisterResult:
    """把富途 MCP server 幂等写入 settings.json 的 mcp_servers。

    Returns:
        ``RegisterResult``：``changed`` 表示是否发生写入。
    """
    settings: dict = {}
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            settings = {}

    servers = settings.get("mcp_servers")
    if not isinstance(servers, dict):
        servers = {}
    desired = _desired_config()
    if servers.get(SERVER_NAME) == desired:
        return RegisterResult(changed=False, settings_path=SETTINGS_PATH)

    servers[SERVER_NAME] = desired
    settings["mcp_servers"] = servers
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass
    return RegisterResult(changed=True, settings_path=SETTINGS_PATH)
