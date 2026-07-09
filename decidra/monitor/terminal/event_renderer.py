"""StreamEvent 到 transcript 的渲染映射。

将 OpenHarness 引擎的七类 ``StreamEvent`` 映射为终端 transcript 的文本行。按
事件类名分派（不 import openharness 类型），对 wheel/源码签名漂移免疫，且便于
测试。

文本增量（``AssistantTextDelta``）是高频事件，``RichLog`` 为块式写入模型，故
累积到缓冲、在边界事件处一次性 flush（合并写入降抖动），而非逐 delta 写入。
"""

from __future__ import annotations

import json
from typing import Callable

WriteCallback = Callable[[str], None]

# 各类事件的渲染样式（markup 前缀）。
_STYLE_TOOL_START = "cyan"
_STYLE_TOOL_OK = "green"
_STYLE_TOOL_ERR = "red"
_STYLE_ERROR = "bold red"
_STYLE_STATUS = "dim"
_STYLE_COMPACT = "dim"
_STYLE_USAGE = "dim"


def _truncate(text: str, limit: int) -> str:
    """将文本截断到 limit 字符，超出加省略号。"""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _summarize_input(tool_input: object, limit: int) -> str:
    """将工具入参摘要为单行短字符串。"""
    if not tool_input:
        return ""
    try:
        raw = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        raw = str(tool_input)
    return _truncate(raw, limit)


class TranscriptRenderer:
    """把 ``StreamEvent`` 渲染到 transcript 的回调对象。

    实例的 ``handle`` 协程可直接作为 ``handle_line`` 的 ``render_event`` 回调。
    高频文本增量累积到内部缓冲，在遇到非文本事件或回合完成时 flush。

    Attributes:
        show_usage: 回合完成时是否显示 token 用量。
        tool_input_limit: 工具入参摘要的最大长度。
        tool_output_limit: 工具输出摘要的最大长度。
    """

    def __init__(
        self,
        write: WriteCallback,
        *,
        show_usage: bool = True,
        tool_input_limit: int = 200,
        tool_output_limit: int = 400,
    ) -> None:
        """初始化渲染器。

        Args:
            write: 向 transcript 追加一行的回调（同步）。
            show_usage: 回合完成时是否显示 token 用量。
            tool_input_limit: 工具入参摘要的最大长度。
            tool_output_limit: 工具输出摘要的最大长度。
        """
        self._write = write
        self.show_usage = show_usage
        self.tool_input_limit = tool_input_limit
        self.tool_output_limit = tool_output_limit
        self._assistant_buf: list[str] = []

    async def handle(self, event: object) -> None:
        """渲染单个事件（``render_event`` 回调）。

        Args:
            event: 任一 ``StreamEvent`` 实例。
        """
        name = type(event).__name__
        if name == "AssistantTextDelta":
            # 高频增量：仅累积，不立即写入。
            text = getattr(event, "text", "")
            if text:
                self._assistant_buf.append(text)
            return

        # 其余事件均为边界：先 flush 累积的助手文本，再渲染事件本身。
        self.flush()

        if name == "AssistantTurnComplete":
            self._render_turn_complete(event)
        elif name == "ToolExecutionStarted":
            self._render_tool_started(event)
        elif name == "ToolExecutionCompleted":
            self._render_tool_completed(event)
        elif name == "ErrorEvent":
            message = getattr(event, "message", "")
            self._write(f"[{_STYLE_ERROR}]✗ 错误: {message}[/{_STYLE_ERROR}]")
        elif name == "StatusEvent":
            message = getattr(event, "message", "")
            if message:
                self._write(f"[{_STYLE_STATUS}]· {message}[/{_STYLE_STATUS}]")
        elif name == "CompactProgressEvent":
            self._render_compact(event)
        # 未知事件类型静默忽略（对上游新增事件向前兼容）。

    def flush(self) -> None:
        """把累积的助手文本作为一个块写入 transcript 并清空缓冲。"""
        if not self._assistant_buf:
            return
        text = "".join(self._assistant_buf).strip()
        self._assistant_buf.clear()
        if text:
            self._write(text)

    def _render_turn_complete(self, event: object) -> None:
        """渲染回合完成（可选 token 用量）。"""
        if not self.show_usage:
            return
        usage = getattr(event, "usage", None)
        if usage is None:
            return
        tokens_in = getattr(usage, "input_tokens", None)
        tokens_out = getattr(usage, "output_tokens", None)
        if tokens_in is None and tokens_out is None:
            return
        self._write(
            f"[{_STYLE_USAGE}]—— tokens in={tokens_in or 0} out={tokens_out or 0}[/{_STYLE_USAGE}]"
        )

    def _render_tool_started(self, event: object) -> None:
        """渲染工具开始执行。"""
        tool_name = getattr(event, "tool_name", "?")
        summary = _summarize_input(getattr(event, "tool_input", None), self.tool_input_limit)
        line = f"[{_STYLE_TOOL_START}]⚙ 调用 {tool_name}[/{_STYLE_TOOL_START}]"
        if summary:
            line += f" [{_STYLE_STATUS}]{summary}[/{_STYLE_STATUS}]"
        self._write(line)

    def _render_tool_completed(self, event: object) -> None:
        """渲染工具执行完成（区分成功/失败）。"""
        tool_name = getattr(event, "tool_name", "?")
        is_error = bool(getattr(event, "is_error", False))
        output = _truncate(str(getattr(event, "output", "") or ""), self.tool_output_limit)
        if is_error:
            line = f"[{_STYLE_TOOL_ERR}]✗ {tool_name} 失败[/{_STYLE_TOOL_ERR}]"
        else:
            line = f"[{_STYLE_TOOL_OK}]✓ {tool_name} 完成[/{_STYLE_TOOL_OK}]"
        if output:
            line += f" [{_STYLE_STATUS}]{output}[/{_STYLE_STATUS}]"
        self._write(line)

    def _render_compact(self, event: object) -> None:
        """渲染上下文压缩进度。"""
        message = getattr(event, "message", None)
        phase = getattr(event, "phase", "")
        text = message or phase
        if text:
            self._write(f"[{_STYLE_COMPACT}]⟳ 压缩: {text}[/{_STYLE_COMPACT}]")
