"""终端控制台的权限与追问对话框。

为 OpenHarness 引擎提供 Textual 对话框式的 ``permission_prompt`` 与
``ask_user_prompt`` 回调。引擎在工具需要确认或 agent 需要向用户追问时，会
``await`` 这些回调；回调内以 ``push_screen_wait`` 弹出模态对话框并等待用户选择。

保守语义：``PermissionDialog`` 默认聚焦「拒绝」，回车/ESC 均视为拒绝，避免误批
准破坏性工具执行。
"""

from __future__ import annotations

from typing import Awaitable, Callable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]


class PermissionDialog(ModalScreen[bool]):
    """工具执行审批对话框。

    展示待执行的工具名与原因，返回用户是否批准。默认聚焦「拒绝」，回车与 ESC
    均返回 ``False``（保守拒绝）。

    Attributes:
        tool_name: 待执行的工具名。
        reason: 引擎给出的需确认原因。
    """

    DEFAULT_CSS = """
    PermissionDialog {
        align: center middle;
    }

    PermissionDialog .dialog-box {
        width: 70%;
        max-width: 90;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $warning;
    }

    PermissionDialog .dialog-title {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    PermissionDialog .dialog-tool {
        width: 1fr;
        text-style: bold;
        margin-bottom: 1;
    }

    PermissionDialog .dialog-reason {
        width: 1fr;
        color: $text-muted;
        margin-bottom: 1;
    }

    PermissionDialog .button-row {
        width: 1fr;
        height: auto;
        align-horizontal: center;
    }

    PermissionDialog .button-row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "deny", "拒绝", priority=True),
    ]

    def __init__(self, tool_name: str, reason: str, **kwargs: object) -> None:
        """初始化权限对话框。

        Args:
            tool_name: 待执行的工具名。
            reason: 需确认原因。
            **kwargs: 透传给 ``ModalScreen``。
        """
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.reason = reason

    def compose(self) -> ComposeResult:
        """组合对话框布局。"""
        with Vertical(classes="dialog-box"):
            yield Static("⚠ 工具执行审批", classes="dialog-title")
            yield Static(f"工具: {self.tool_name}", classes="dialog-tool")
            yield Static(self.reason or "该工具请求需要确认。", classes="dialog-reason")
            with Horizontal(classes="button-row"):
                yield Button("拒绝", variant="error", id="deny-btn")
                yield Button("批准", variant="success", id="approve-btn")

    def on_mount(self) -> None:
        """挂载后聚焦「拒绝」，保守默认。"""
        self.query_one("#deny-btn", Button).focus()

    @on(Button.Pressed, "#approve-btn")
    def _on_approve(self, event: Button.Pressed) -> None:
        """批准：返回 True。"""
        event.stop()
        self.dismiss(True)

    @on(Button.Pressed, "#deny-btn")
    def _on_deny(self, event: Button.Pressed) -> None:
        """拒绝：返回 False。"""
        event.stop()
        self.dismiss(False)

    def action_deny(self) -> None:
        """ESC 动作：拒绝。"""
        self.dismiss(False)


class AskUserDialog(ModalScreen[str]):
    """agent 追问输入对话框。

    展示 agent 提出的问题，返回用户输入文本。ESC 或空提交返回空串。

    Attributes:
        question: agent 向用户提出的问题。
    """

    DEFAULT_CSS = """
    AskUserDialog {
        align: center middle;
    }

    AskUserDialog .dialog-box {
        width: 70%;
        max-width: 90;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    AskUserDialog .dialog-title {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    AskUserDialog .dialog-question {
        width: 1fr;
        margin-bottom: 1;
    }

    AskUserDialog Input {
        margin-bottom: 1;
    }

    AskUserDialog .button-row {
        width: 1fr;
        height: auto;
        align-horizontal: center;
    }

    AskUserDialog .button-row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消", priority=True),
    ]

    def __init__(self, question: str, **kwargs: object) -> None:
        """初始化追问对话框。

        Args:
            question: agent 提出的问题。
            **kwargs: 透传给 ``ModalScreen``。
        """
        super().__init__(**kwargs)
        self.question = question

    def compose(self) -> ComposeResult:
        """组合对话框布局。"""
        with Vertical(classes="dialog-box"):
            yield Static("💬 需要你的输入", classes="dialog-title")
            yield Static(self.question, classes="dialog-question")
            yield Input(placeholder="输入回复，回车提交…", id="answer-input")
            with Horizontal(classes="button-row"):
                yield Button("取消", variant="error", id="cancel-btn")
                yield Button("提交", variant="success", id="submit-btn")

    def on_mount(self) -> None:
        """挂载后聚焦输入框。"""
        self.query_one("#answer-input", Input).focus()

    @on(Input.Submitted, "#answer-input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        """回车提交。"""
        event.stop()
        self.dismiss(event.value.strip())

    @on(Button.Pressed, "#submit-btn")
    def _on_submit(self, event: Button.Pressed) -> None:
        """提交：返回输入文本。"""
        event.stop()
        self.dismiss(self.query_one("#answer-input", Input).value.strip())

    @on(Button.Pressed, "#cancel-btn")
    def _on_cancel(self, event: Button.Pressed) -> None:
        """取消：返回空串。"""
        event.stop()
        self.dismiss("")

    def action_cancel(self) -> None:
        """ESC 动作：取消。"""
        self.dismiss("")


def make_permission_callbacks(app: App) -> tuple[PermissionPrompt, AskUserPrompt]:
    """基于给定 App 产出权限与追问回调。

    产出的回调在 App 事件循环内以 ``push_screen_wait`` 弹出模态对话框并等待
    用户选择。回调须在 worker 上下文中被 ``await``（终端提交经 ``run_worker``
    驱动，满足此约束）。

    Args:
        app: 承载对话框的 Textual App。

    Returns:
        ``(permission_prompt, ask_user_prompt)`` 二元组。
    """

    async def permission_prompt(tool_name: str, reason: str) -> bool:
        """弹权限对话框，返回是否批准。"""
        return await app.push_screen_wait(PermissionDialog(tool_name, reason))

    async def ask_user_prompt(question: str) -> str:
        """弹追问对话框，返回用户输入。"""
        return await app.push_screen_wait(AskUserDialog(question))

    return permission_prompt, ask_user_prompt
