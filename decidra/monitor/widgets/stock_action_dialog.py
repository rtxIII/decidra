"""股票操作菜单对话框。

监控股票列表光标行按回车弹出：进入 K 线分析 / 删除该股票 / 加入(移出)策略监控。
选项由 ``build_stock_menu_options`` 纯函数构造（动作 id 稳定，供调用方路由分发），
本模块只负责 Textual 交互，不依赖 strategy 包。
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

# 动作 id：调用方按此路由分发，勿改动
ACTION_ANALYSIS = "analysis"
ACTION_DELETE = "delete"
ACTION_STRATEGY_ADD = "strategy_add"
ACTION_STRATEGY_REMOVE = "strategy_remove"


def build_stock_menu_options(
    stock_code: str, in_strategy_watchlist: bool
) -> List[Tuple[str, str]]:
    """构造股票操作菜单选项。

    Args:
        stock_code: 富途股票代码。
        in_strategy_watchlist: 是否已在策略 watchlist 中（决定第三项为加入还是移出）。

    Returns:
        (action_id, markup 标签) 列表。
    """
    options = [
        (ACTION_ANALYSIS, "📈 进入 K 线分析"),
        (ACTION_DELETE, "[red]🗑 删除该股票[/red]"),
    ]
    if in_strategy_watchlist:
        options.append((ACTION_STRATEGY_REMOVE, "[yellow]▶ 移出策略监控[/yellow]"))
    else:
        options.append((ACTION_STRATEGY_ADD, "[yellow]▶ 加入策略监控[/yellow]"))
    return options


class StockActionDialog(ModalScreen[Optional[str]]):
    """股票操作菜单。

    回车返回选中的动作 id，ESC 取消返回 ``None``。

    Attributes:
        stock_code: 富途股票代码。
        display_name: 股票展示名称。
        options: (action_id, markup 标签) 列表。
    """

    DEFAULT_CSS = """
    StockActionDialog {
        align: center middle;
    }

    StockActionDialog .dialog-box {
        width: 50%;
        max-width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    StockActionDialog .dialog-title {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    StockActionDialog OptionList {
        height: auto;
        max-height: 10;
        background: $surface;
    }

    StockActionDialog .dialog-hint {
        width: 1fr;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消", priority=True),
        # 空格=确认：菜单由空格键唤出，连按空格即可选中首项（K线分析）
        Binding("space", "confirm", "确认"),
        # w/s 与 ↑↓ 等效（主界面光标键位习惯延续进菜单；App 层的 w/s 绑定
        # 被模态屏截断，须在此重建；不进提示行）
        Binding("w", "cursor_up", "上移", show=False),
        Binding("s", "cursor_down", "下移", show=False),
    ]

    def __init__(
        self,
        stock_code: str,
        display_name: str,
        options: List[Tuple[str, str]],
        **kwargs: object,
    ) -> None:
        """初始化操作菜单对话框。

        Args:
            stock_code: 富途股票代码。
            display_name: 股票展示名称（缺省时传股票代码即可）。
            options: (action_id, markup 标签) 列表。
            **kwargs: 透传给 ``ModalScreen``。
        """
        super().__init__(**kwargs)
        self.stock_code = stock_code
        self.display_name = display_name
        self.options = options

    def compose(self) -> ComposeResult:
        """组合对话框布局。"""
        if self.display_name and self.display_name != self.stock_code:
            title = f"📋 {self.display_name} ({self.stock_code})"
        else:
            title = f"📋 {self.stock_code}"
        with Vertical(classes="dialog-box"):
            # 标题含真实股票名，包成 Text 纯文本避免名称中的 [ 被当 markup 解析
            yield Static(Text(title), classes="dialog-title")
            yield OptionList(
                *[
                    Option(Text.from_markup(label), id=action_id)
                    for action_id, label in self.options
                ],
                id="stock-action-options",
            )
            yield Static("↑↓ 选择 · 空格/回车确认 · ESC 取消", classes="dialog-hint")

    def on_mount(self) -> None:
        """挂载后聚焦选项列表。"""
        self.query_one("#stock-action-options", OptionList).focus()

    @on(OptionList.OptionSelected, "#stock-action-options")
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        """回车选中：返回该动作 id。"""
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """ESC 动作：取消选择。"""
        self.dismiss(None)

    def action_confirm(self) -> None:
        """空格动作：确认当前高亮项（与回车等效）。"""
        option_list = self.query_one("#stock-action-options", OptionList)
        option_list.action_select()

    def action_cursor_up(self) -> None:
        """w 键：高亮上移（与 ↑ 等效）。"""
        self.query_one("#stock-action-options", OptionList).action_cursor_up()

    def action_cursor_down(self) -> None:
        """s 键：高亮下移（与 ↓ 等效）。"""
        self.query_one("#stock-action-options", OptionList).action_cursor_down()
