"""终端 /enrich 命令：解析与告警选择对话框。

``/enrich`` 不带参数时弹出 ``AlertPickDialog``：上下键在最近告警中选择，回车
确认、ESC 取消。选项数据由 ``decidra.strategy.display.build_alert_options``
产出（纯函数，含研判状态标记），本模块只负责命令识别与 Textual 交互，不依赖
strategy 包（保持面板可脱离 openharness 导入）。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

ENRICH_COMMAND = "/enrich"
ENRICH_COMMAND_DESCRIPTION = "研判策略告警（弹窗选择，或 /enrich <id> 直达）"


def parse_enrich_command(line: str) -> Optional[str]:
    """解析终端输入是否为 /enrich 命令。

    Args:
        line: 用户输入行。

    Returns:
        ``None``: 不是 /enrich 命令（含 ``/enrichxx`` 这类同前缀他词）；
        ``""``: 无参数，应弹选择对话框；
        其余: 告警短码 id（已去 ``#`` 前缀与空白）。
    """
    line = line.strip()
    if not line.startswith(ENRICH_COMMAND):
        return None
    rest = line[len(ENRICH_COMMAND):]
    if rest and rest[0] not in (" ", "#"):
        return None
    return rest.strip().lstrip("#").strip()


class AlertPickDialog(ModalScreen[Optional[str]]):
    """策略告警选择对话框。

    展示最近告警（新→旧），回车返回选中的告警短码 id，ESC 取消返回 ``None``。

    Attributes:
        options: (alert_id, markup 单行) 列表。
    """

    DEFAULT_CSS = """
    AlertPickDialog {
        align: center middle;
    }

    AlertPickDialog .dialog-box {
        width: 80%;
        max-width: 100;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    AlertPickDialog .dialog-title {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    AlertPickDialog OptionList {
        height: auto;
        max-height: 14;
        background: $surface;
    }

    AlertPickDialog .dialog-hint {
        width: 1fr;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消", priority=True),
    ]

    def __init__(self, options: List[Tuple[str, str]], **kwargs: object) -> None:
        """初始化选择对话框。

        Args:
            options: (alert_id, markup 单行) 列表，新→旧。
            **kwargs: 透传给 ``ModalScreen``。
        """
        super().__init__(**kwargs)
        self.options = options

    def compose(self) -> ComposeResult:
        """组合对话框布局。"""
        with Vertical(classes="dialog-box"):
            yield Static("🔎 选择要研判的告警", classes="dialog-title")
            yield OptionList(
                *[Option(Text.from_markup(line), id=alert_id) for alert_id, line in self.options],
                id="alert-options",
            )
            yield Static("↑↓ 选择 · 回车确认 · ESC 取消", classes="dialog-hint")

    def on_mount(self) -> None:
        """挂载后聚焦选项列表。"""
        self.query_one("#alert-options", OptionList).focus()

    @on(OptionList.OptionSelected, "#alert-options")
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        """回车选中：返回该告警 id。"""
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """ESC 动作：取消选择。"""
        self.dismiss(None)
