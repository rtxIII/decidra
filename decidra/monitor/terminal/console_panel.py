"""终端控制台面板 - 监控主界面下半部分的 agent 交互组件。

以 ``RichLog`` 作为流式输出 transcript、``Input`` 作为输入框，替换原
``InfoPanel``。T7 提供布局骨架与 transcript 写入原语；事件渲染（T8）与提交
驱动（T9）在其上构建。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Input, RichLog

from ...utils.global_vars import get_logger
from .event_renderer import TranscriptRenderer

if TYPE_CHECKING:
    from .runtime_bridge import TerminalRuntime

TRANSCRIPT_ID = "terminal_transcript"
INPUT_ID = "terminal_input"


class TerminalConsolePanel(Widget):
    """终端控制台面板。

    上部为滚动 transcript（``RichLog``），底部为输入框（``Input``）。输入提交经
    Textual ``run_worker`` 驱动 ``TerminalRuntime.submit``，事件经
    ``TranscriptRenderer`` 渲染到 transcript。长回合可用 ESC 取消。

    需在使用前通过 ``set_runtime`` 注入一个 ``TerminalRuntime``；未注入时输入仅
    回显提示，不驱动引擎（便于脱离引擎单独渲染）。

    Attributes:
        border_title: 面板边框标题。
    """

    BINDINGS = [
        Binding("escape", "cancel_turn", "取消", show=False),
    ]

    DEFAULT_CSS = """
    TerminalConsolePanel {
        layout: vertical;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        background: $panel;
        height: 1fr;
        width: 1fr;
    }

    TerminalConsolePanel:focus-within {
        border: heavy $accent;
    }

    TerminalConsolePanel #terminal_transcript {
        height: 1fr;
        width: 1fr;
        background: $surface;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    TerminalConsolePanel #terminal_input {
        dock: bottom;
        height: 3;
        border: none;
        border-top: solid $accent;
        background: $surface;
    }
    """

    def __init__(self, title: str = "🖥 智能终端", **kwargs: object) -> None:
        """初始化终端控制台面板。

        Args:
            title: 边框标题。
            **kwargs: 透传给 ``Widget``。
        """
        super().__init__(**kwargs)
        self.border_title = title
        self.logger = get_logger("terminal.console_panel")
        self._runtime: "TerminalRuntime | None" = None
        self._renderer = TranscriptRenderer(self._write_line)
        self._active_worker = None
        self._busy = False

    def compose(self) -> ComposeResult:
        """组合 transcript 与输入框。"""
        yield RichLog(
            id=TRANSCRIPT_ID,
            markup=True,
            wrap=True,
            highlight=False,
            auto_scroll=True,
        )
        yield Input(
            placeholder="输入消息或斜杠命令，回车发送…",
            id=INPUT_ID,
        )

    def on_mount(self) -> None:
        """挂载后写入就绪提示。"""
        self.write_transcript("[dim]智能终端就绪。输入消息与 agent 对话，或用 / 触发命令。[/dim]")

    @property
    def transcript(self) -> RichLog:
        """transcript 输出组件。"""
        return self.query_one(f"#{TRANSCRIPT_ID}", RichLog)

    @property
    def input(self) -> Input:
        """输入框组件。"""
        return self.query_one(f"#{INPUT_ID}", Input)

    def write_transcript(self, content: str | Text) -> None:
        """向 transcript 追加一条内容。

        Args:
            content: markup 字符串或 rich ``Text``。
        """
        self.transcript.write(content)

    def focus_input(self) -> None:
        """将焦点移到输入框。"""
        self.input.focus()

    def clear_transcript(self) -> None:
        """清空 transcript。"""
        self.transcript.clear()

    def set_runtime(self, runtime: "TerminalRuntime") -> None:
        """注入 agent 运行时。

        Args:
            runtime: 已构造的 ``TerminalRuntime``（可尚未 ``start``）。
        """
        self._runtime = runtime

    def _write_line(self, content: str | Text) -> None:
        """renderer 使用的写入回调（挂载后安全）。"""
        try:
            self.transcript.write(content)
        except Exception:
            # transcript 尚未挂载时忽略（渲染前不应发生）。
            self.logger.debug("transcript 尚未就绪，丢弃一行输出")

    @on(Input.Submitted, "#terminal_input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        """输入提交：清空输入框并经 worker 驱动一轮引擎。"""
        event.stop()
        line = event.value.strip()
        self.input.value = ""
        if not line:
            return
        if self._busy:
            self.write_transcript("[dim]· 上一轮仍在进行，请稍候或按 ESC 取消[/dim]")
            return
        # 回显用户输入
        self.write_transcript(f"[bold]›[/bold] {line}")
        if self._runtime is None:
            self.write_transcript("[dim]· 未接入运行时（仅回显）[/dim]")
            return
        self._active_worker = self.run_worker(
            self._drive(line),
            group="terminal_turn",
            exclusive=True,
            description="agent turn",
        )

    async def _drive(self, line: str) -> None:
        """在 worker 中驱动一轮引擎。

        权限回调经 ``push_screen_wait`` 弹窗，要求 worker 上下文，本方法满足。
        结束时 flush 渲染器缓冲，并把焦点交还输入框。

        Args:
            line: 用户输入行。
        """
        self._busy = True
        try:
            await self._runtime.submit(
                line,
                render_event=self._renderer.handle,
                print_system=self._print_system,
            )
        except asyncio.CancelledError:
            self._renderer.flush()
            self.write_transcript("[yellow]· 已取消本轮[/yellow]")
            raise
        except Exception as exc:  # 防御：任何未预期异常不应崩溃 UI
            self._renderer.flush()
            self.write_transcript(f"[bold red]✗ 运行时错误: {exc}[/bold red]")
            self.logger.error("驱动 agent 回合失败: %s", exc)
        else:
            self._renderer.flush()
        finally:
            self._busy = False
            self._active_worker = None
            self.focus_input()

    async def _print_system(self, message: str) -> None:
        """系统消息回调：以 dim 样式写入 transcript。"""
        self.write_transcript(f"[dim]· {message}[/dim]")

    def action_cancel_turn(self) -> None:
        """ESC：取消进行中的回合。"""
        if self._active_worker is not None and self._busy:
            self._active_worker.cancel()

