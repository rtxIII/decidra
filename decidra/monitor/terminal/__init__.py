"""Decidra 终端控制台 - OpenHarness/ohmo 交互内核桥接层。

本包将 OpenHarness 引擎以进程内方式嵌入 Decidra 的 Textual 事件循环，
为监控主界面下半部分的终端控制台提供 agent 交互能力（skill / memory / workflow）。

设计要点：纯 Textual UI 模块（console_panel / event_renderer / info_sink /
permission_dialogs / auth_migrate）在此急加载，**不依赖 openharness**；而
``runtime_bridge`` 依赖 openharness，改为按需懒加载（PEP 562 ``__getattr__``），
使 openharness 缺失或异常时主界面仍能加载终端面板并优雅降级，而非崩溃。
"""

from typing import TYPE_CHECKING

from .auth_migrate import MigrationResult, migrate_ai_config
from .console_panel import TerminalConsolePanel
from .event_renderer import TranscriptRenderer
from .info_sink import InfoSink
from .permission_dialogs import (
    AskUserDialog,
    PermissionDialog,
    make_permission_callbacks,
)

# runtime_bridge 依赖 openharness，懒加载的符号。
_LAZY = {"TerminalRuntime", "AuthStatus", "check_auth"}

if TYPE_CHECKING:  # 仅供类型检查/IDE，不在运行时急加载 openharness
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


def __getattr__(name: str):
    """按需从 runtime_bridge 加载 openharness 相关符号（PEP 562）。"""
    if name in _LAZY:
        from . import runtime_bridge
        return getattr(runtime_bridge, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
