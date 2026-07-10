"""Decidra 终端控制台 - OpenHarness/ohmo 交互内核桥接层。

本包将 OpenHarness 引擎以进程内方式嵌入 Decidra 的 Textual 事件循环，
为监控主界面下半部分的终端控制台提供 agent 交互能力（skill / memory / workflow）。
"""

from .auth_migrate import MigrationResult, migrate_ai_config
from .console_panel import TerminalConsolePanel
from .event_renderer import TranscriptRenderer
from .info_sink import InfoSink
from .permission_dialogs import (
    AskUserDialog,
    PermissionDialog,
    make_permission_callbacks,
)
from .runtime_bridge import AuthStatus, TerminalRuntime, check_auth

__all__ = [
    "TerminalConsolePanel",
    "TranscriptRenderer",
    "TerminalRuntime",
    "AuthStatus",
    "check_auth",
    "migrate_ai_config",
    "MigrationResult",
    "InfoSink",
    "PermissionDialog",
    "AskUserDialog",
    "make_permission_callbacks",
]
