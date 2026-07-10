"""InfoSink 日志面契约。

原 ``InfoPanel`` 被 6 处外部调用点（ui.py / lifecycle.py / user.py /
event_handler.py / main/data.py 及 monitor_app.py）以 ``log_info`` 等方法记录日志。
``TerminalConsolePanel`` 完全替换 ``InfoPanel`` 后，须实现相同的日志接口，使这些
调用点无需改动即可把日志转发到终端 transcript。

本 Protocol 声明这些调用点实际依赖的方法，供类型检查确认终端面板与调用点签名
一致（结构化子类型，无需显式继承）。方法多为 async，与原 ``InfoPanel`` 保持一致。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class InfoSink(Protocol):
    """日志面契约：终端面板须实现，以兼容原 InfoPanel 调用点。"""

    async def log_info(self, content: str, source: str = "") -> None:
        """记录一条信息日志。"""
        ...

    async def log_warning(self, content: str, source: str = "") -> None:
        """记录一条警告日志。"""
        ...

    async def log_error(self, content: str, source: str = "") -> None:
        """记录一条错误日志。"""
        ...

    async def log_debug(self, content: str, source: str = "") -> None:
        """记录一条调试日志。"""
        ...

    async def add_info(
        self,
        content: str,
        info_type: Any = None,
        level: Any = None,
        source: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """记录一条带类型/级别的信息。"""
        ...

    def set_trade_manager(self, trade_manager: Any) -> None:
        """设置交易管理器引用。"""
        ...

    async def clear_all(self) -> None:
        """清空日志显示。"""
        ...

    async def select_last_message(self) -> bool:
        """选中最后一条消息（兼容用，终端场景为空操作）。"""
        ...
