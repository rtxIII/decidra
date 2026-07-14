"""终端控制台面板 - 监控主界面下半部分的 agent 交互组件。

以 ``RichLog`` 作为流式输出 transcript、``Input`` 作为输入框，替换原
``InfoPanel``。T7 提供布局骨架与 transcript 写入原语；事件渲染（T8）与提交
驱动（T9）在其上构建。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static
from textual.worker import get_current_worker

from ...utils.global_vars import get_logger
from .enrich_dialog import (
    ENRICH_COMMAND,
    ENRICH_COMMAND_DESCRIPTION,
    AlertPickDialog,
    parse_enrich_command,
)
from .event_renderer import TranscriptRenderer

if TYPE_CHECKING:
    from .runtime_bridge import TerminalRuntime

TRANSCRIPT_ID = "terminal_transcript"
INPUT_ID = "terminal_input"
HINTS_ID = "terminal_command_hints"
# 提示条最多展示的命令条数（超出以 … 提示）
MAX_COMMAND_HINTS = 8


def filter_command_hints(
    value: str, commands: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """按输入前缀过滤斜杠命令提示。

    Args:
        value: 当前输入框内容。
        commands: (name, description) 列表，name 不含斜杠。

    Returns:
        名字以已输入前缀开头的 (name, description)；输入非 ``/`` 开头或已出现
        空格（开始输入参数）时返回空。
    """
    value = value.lstrip()
    if not value.startswith("/") or " " in value:
        return []
    prefix = value[1:]
    return [(name, desc) for name, desc in commands if name.startswith(prefix)]


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

    TerminalConsolePanel #terminal_command_hints {
        dock: bottom;
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $surface;
        border-top: solid $accent;
        display: none;
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
        self._trade_manager: object = None
        # 斜杠命令提示缓存：拿到运行时命令列表后才缓存（此前只有内置命令）
        self._commands_cache: list[tuple[str, str]] | None = None

    def compose(self) -> ComposeResult:
        """组合 transcript、输入框与命令提示条（提示条停靠在输入框上方）。"""
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
        yield Static("", id=HINTS_ID)

    def on_mount(self) -> None:
        """挂载后写入就绪提示。"""
        self.write_transcript(
            "[dim]智能终端就绪。输入消息与 agent 对话，输入 / 查看可用命令；"
            f"{ENRICH_COMMAND} 从最近策略告警中选择一条交给 agent 复核。[/dim]"
        )

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

    @on(Input.Changed, "#terminal_input")
    def _on_input_changed(self, event: Input.Changed) -> None:
        """输入变化：以 ``/`` 开头时在输入框上方展示匹配的命令提示。"""
        event.stop()
        self._refresh_command_hints(event.value)

    def _refresh_command_hints(self, value: str) -> None:
        """按当前输入刷新命令提示条（无匹配时隐藏）。"""
        hints = self.query_one(f"#{HINTS_ID}", Static)
        matches = filter_command_hints(value, self._available_commands())
        if not matches:
            hints.display = False
            return
        parts = [
            f"[bold]/{escape(name)}[/bold] [dim]{escape(desc)}[/dim]"
            for name, desc in matches[:MAX_COMMAND_HINTS]
        ]
        if len(matches) > MAX_COMMAND_HINTS:
            parts.append("[dim]…[/dim]")
        hints.update("  ".join(parts))
        hints.display = True

    def _available_commands(self) -> list[tuple[str, str]]:
        """内置命令 + 运行时注册的斜杠命令（(name, description)，name 不含斜杠）。

        运行时命令要等 bundle 就绪才可得：取到前每次现查（只有内置命令，不缓存），
        取到后缓存并给输入框挂上内联补全 suggester。
        """
        if self._commands_cache is not None:
            return self._commands_cache
        commands = [(ENRICH_COMMAND.lstrip("/"), ENRICH_COMMAND_DESCRIPTION)]
        runtime_commands: list[tuple[str, str]] = []
        if self._runtime is not None:
            try:
                runtime_commands = self._runtime.list_slash_commands()
            except Exception as exc:
                self.logger.debug("获取运行时命令列表失败: %s", exc)
        known = {name for name, _ in commands}
        commands += [(n, d) for n, d in runtime_commands if n not in known]
        if runtime_commands:
            self._commands_cache = commands
            self.input.suggester = SuggestFromList(
                [f"/{name}" for name, _ in commands], case_sensitive=True
            )
        return commands

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
        # 回显用户输入（转义 markup，防注入破坏渲染）
        self.write_transcript(f"[bold]›[/bold] {escape(line)}")
        if self._runtime is None:
            self.write_transcript("[dim]· 未接入运行时（仅回显）[/dim]")
            return
        # 在启动 worker 之前同步置忙，关闭 handler 与 worker 之间的竞态窗口。
        self._busy = True
        enrich_arg = parse_enrich_command(line)
        turn = self._drive(line) if enrich_arg is None else self._drive_enrich(enrich_arg or None)
        self._active_worker = self.run_worker(
            turn,
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
            self.write_transcript(f"[bold red]✗ 运行时错误: {escape(str(exc))}[/bold red]")
            self.logger.error("驱动 agent 回合失败: %s", exc)
        else:
            self._renderer.flush()
        finally:
            self._finish_turn_if_current()

    def _finish_turn_if_current(self) -> None:
        """仅当自己仍是当前 worker 时清忙态并交还焦点。

        避免被 exclusive 取消的旧 worker 的收尾清掉后继 worker 的引用
        （否则 ESC 取消会失效）。
        """
        try:
            current = get_current_worker()
        except Exception:
            current = None
        if current is None or current is self._active_worker:
            self._busy = False
            self._active_worker = None
            self.focus_input()

    async def _drive_enrich(self, alert_id: str | None) -> None:
        """/enrich 入口：无 id 时弹告警选择对话框，选定后构造研判 prompt 驱动引擎。

        Args:
            alert_id: 告警短码 id；``None`` 表示未指定，需弹窗选择。
        """
        prompt: str | None = None
        try:
            # 延迟导入：strategy 包依赖 openharness，保持面板可脱离其导入。
            # 路径经模块属性在调用时解析（与 strategy_server 一致，测试可替换）。
            from ...strategy import alerts as alerts_mod
            from ...strategy.display import build_alert_options, build_enrich_prompt

            resolved = alert_id
            if resolved is None:
                options = build_alert_options(
                    alerts_path=alerts_mod.ALERTS_PATH,
                    enrichments_path=alerts_mod.ENRICHMENTS_PATH,
                )
                if not options:
                    self.write_transcript("[dim]· 暂无策略告警可研判[/dim]")
                    return
                resolved = await self.app.push_screen_wait(AlertPickDialog(options))
                if resolved is None:
                    self.write_transcript("[dim]· 已取消研判[/dim]")
                    return
            alert = alerts_mod.find_alert(resolved, alerts_mod.ALERTS_PATH)
            if alert is None:
                self.write_transcript(
                    f"[yellow]· 未找到告警 #{escape(resolved)}，"
                    f"可用 {ENRICH_COMMAND} 重新选择[/yellow]"
                )
                return
            self.write_transcript(
                f"[dim]· 研判 #{alert.get('id')} {alert.get('symbol')} {alert.get('action')}[/dim]"
            )
            prompt = build_enrich_prompt(alert)
        except Exception as exc:
            self.write_transcript(f"[bold red]✗ 研判入口错误: {escape(str(exc))}[/bold red]")
            self.logger.error("研判选择流程失败: %s", exc)
            return
        finally:
            if prompt is None:
                # 未进入引擎回合（取消/无告警/异常）：自行收尾
                self._finish_turn_if_current()
        await self._drive(prompt)

    async def _print_system(self, message: str) -> None:
        """系统消息回调：以 dim 样式写入 transcript（转义 markup）。"""
        self.write_transcript(f"[dim]· {escape(message)}[/dim]")

    def action_cancel_turn(self) -> None:
        """ESC：取消进行中的回合。"""
        if self._active_worker is not None and self._busy:
            self._active_worker.cancel()

    # —— InfoSink 兼容 shim ——
    # 原 InfoPanel 被 6 处调用点以 log_info 等记录日志。终端面板实现相同接口，
    # 把日志转发到 transcript，使这些调用点无需改动即可工作。

    _LEVEL_STYLE = {
        "info": "dim",
        "warning": "yellow",
        "error": "red",
        "debug": "dim",
    }

    def _log(self, content: str, level: str, source: str) -> None:
        """把一条日志按级别样式写入 transcript（转义 markup 防注入）。"""
        style = self._LEVEL_STYLE.get(level, "dim")
        prefix = f"[{escape(source)}] " if source else ""
        self.write_transcript(f"[{style}]· {prefix}{escape(content)}[/{style}]")

    async def log_info(self, content: str, source: str = "") -> None:
        """记录信息日志（转发到 transcript）。"""
        self._log(content, "info", source)

    async def log_warning(self, content: str, source: str = "") -> None:
        """记录警告日志（转发到 transcript）。"""
        self._log(content, "warning", source)

    async def log_error(self, content: str, source: str = "") -> None:
        """记录错误日志（转发到 transcript）。"""
        self._log(content, "error", source)

    async def log_debug(self, content: str, source: str = "") -> None:
        """记录调试日志（转发到 transcript）。"""
        self._log(content, "debug", source)

    async def add_info(
        self,
        content: str,
        info_type: object = None,
        level: object = None,
        source: str = "",
        data: dict | None = None,
    ) -> None:
        """记录一条带类型/级别的信息（转发到 transcript）。

        兼容原 InfoPanel 签名；``info_type``/``level``/``data`` 在终端场景下仅用于
        推断样式，不做结构化存储。
        """
        level_name = getattr(level, "value", None) or (str(level).lower() if level else "info")
        style = self._LEVEL_STYLE.get(level_name, "dim")
        prefix = f"[{escape(source)}] " if source else ""
        self.write_transcript(f"[{style}]· {prefix}{escape(content)}[/{style}]")

    def set_trade_manager(self, trade_manager: object) -> None:
        """设置交易管理器引用（供 agent 交易工具后续使用）。"""
        self._trade_manager = trade_manager

    async def clear_all(self) -> None:
        """清空 transcript（兼容 InfoPanel.clear_all）。"""
        self.clear_transcript()

    async def select_last_message(self) -> bool:
        """兼容 InfoPanel.select_last_message；终端场景为空操作。"""
        return False


