"""
修复后的自动补全输入对话框
"""
from dataclasses import dataclass
from typing import Optional, Callable

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input
from textual.containers import Horizontal, Vertical, Center
from textual.validation import Validator

from textual.css.query import NoMatches
from textual_autocomplete import AutoComplete
from textual_autocomplete._autocomplete import DropdownItem, TargetState


class SafeAutoComplete(AutoComplete):
    """带拆卸守卫的 AutoComplete。

    上游 textual_autocomplete 4.0.4 在 on_mount 中注册了 0.2s 定时器周期性调用
    ``_align_to_target``，该方法通过 ``self.option_list`` (``query_one(AutoCompleteList)``)
    访问下拉列表却未捕获 ``NoMatches``。当承载它的模态对话框 ``dismiss`` 拆卸、
    ``AutoCompleteList`` 子节点已被移除而定时器仍触发时，会抛出未捕获的 ``NoMatches``，
    直接使整个 TUI 崩溃退出（"NoMatches: No nodes match AutoCompleteList on AutoComplete()"）。

    库自身在 ``_listen_to_messages`` 中已用 ``try/except NoMatches`` 处理同类拆卸场景，
    这里对 ``_align_to_target`` 采用一致的守卫，仅吞掉拆卸期的 ``NoMatches``。
    """

    def _align_to_target(self) -> None:
        try:
            super()._align_to_target()
        except NoMatches:
            # 对话框拆卸期，AutoCompleteList 已被移除而定时器仍触发；忽略即可
            return


class WindowInputDialog(ModalScreen):
    """窗口化输入对话框
    
    基于ModalScreen实现的窗口式输入对话框，支持用户输入各种数据和自动补全
    """
    
    DEFAULT_CSS = """
    WindowInputDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }
    
    .input-dialog-window {
        width: 60;
        height: auto;
        max-height: 25;
        background: $surface;
        border: thick $primary;
        border-title-color: $text;
        border-title-background: $primary;
        border-title-style: bold;
        padding: 1 2;
        margin: 2;
    }
    
    .input-dialog-content {
        layout: vertical;
        height: auto;
    }
    
    .input-message-content {
        height: auto;
        text-align: left;
        padding: 1 0;
        color: $text;
        margin-bottom: 1;
    }
    
    .input-field {
        width: 100%;
        margin-bottom: 1;
        border: solid $primary;
    }
    
    .input-field:focus {
        border: solid $accent;
    }
    
    .error-message {
        height: auto;
        color: $error;
        text-align: left;
        padding: 0 0 1 0;
        display: none;
    }
    
    .error-message.visible {
        display: block;
    }
    
    .input-button-row {
        layout: horizontal;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .input-button-row Button {
        margin: 0 1;
        min-width: 12;
    }
    
    .input-dialog-window:focus-within {
        border: thick $accent;
    }
    """
    
    # 键盘绑定
    BINDINGS = [
        Binding("space", "submit", "提交", priority=True),
        Binding("escape", "cancel", "取消", priority=True),
        Binding("ctrl+c", "cancel", "取消"),
    ]

    @dataclass
    class InputResult(Message):
        """输入对话框结果消息"""
        submitted: bool
        value: Optional[str] = None
        dialog_id: Optional[str] = None

    def __init__(
        self, 
        message: str, 
        title: Optional[str] = None,
        placeholder: str = "",
        default_value: str = "",
        input_type: str = "text",
        password: bool = False,
        submit_text: str = "确认",
        cancel_text: str = "取消",
        dialog_id: Optional[str] = None,
        validator: Optional[Validator] = None,
        required: bool = True,
        submit_callback: Optional[Callable[[str], None]] = None,
        cancel_callback: Optional[Callable] = None,
        enable_autocomplete: bool = False,
        candidates_callback: Optional[Callable[[TargetState], list[DropdownItem]]] = None
    ) -> None:
        """初始化窗口化输入对话框
        
        Args:
            message: 要显示的提示信息
            title: 对话框标题，默认为"输入"
            placeholder: 输入框占位符文本
            default_value: 默认输入值
            input_type: 输入类型 ("text", "number", "email" 等)
            password: 是否为密码输入
            submit_text: 提交按钮文本
            cancel_text: 取消按钮文本
            dialog_id: 对话框唯一标识
            validator: 输入验证器
            required: 是否必填
            submit_callback: 提交回调函数
            cancel_callback: 取消回调函数
            enable_autocomplete: 是否启用自动补全功能
            candidates_callback: 自动补全候选项生成回调函数
        """
        super().__init__()
        
        self.message = message
        self.title = title or "输入"
        self.placeholder = placeholder
        self.default_value = default_value
        self.input_type = input_type
        self.password = password
        self.submit_text = submit_text
        self.cancel_text = cancel_text
        self.dialog_id = dialog_id
        self.validator = validator
        self.required = required
        self.submit_callback = submit_callback
        self.cancel_callback = cancel_callback
        self.enable_autocomplete = enable_autocomplete
        self.candidates_callback = candidates_callback
        
        self._input_widget: Optional[Input] = None
        self._error_widget: Optional[Static] = None
        self._autocomplete_widget: Optional[AutoComplete] = None

    def compose(self) -> ComposeResult:
        """构建窗口化输入对话框UI"""
        with Vertical(classes="input-dialog-window") as dialog_window:
            dialog_window.border_title = self.title
            
            with Vertical(classes="input-dialog-content"):
                # 消息显示区域
                yield Static(self.message, classes="input-message-content")
                
                # 输入字段
                if self.enable_autocomplete and self.candidates_callback:
                    # 启用自动补全的输入字段
                    self._input_widget = Input(
                        value=self.default_value,
                        placeholder=self.placeholder,
                        password=self.password,
                        validators=[self.validator] if self.validator else None,
                        classes="input-field",
                        id="input-field"
                    )
                    yield self._input_widget
                    # 用 AutoComplete 包装 Input（使用带拆卸守卫的子类，避免定时器竞态崩溃）
                    self._autocomplete_widget = SafeAutoComplete(
                        self._input_widget,
                        candidates=self.candidates_callback,
                        prevent_default_enter=False,
                        prevent_default_tab=False,
                        #id="autocomplete-wrapper"
                    )
                    yield self._autocomplete_widget
                else:
                    # 普通输入字段
                    self._input_widget = Input(
                        value=self.default_value,
                        placeholder=self.placeholder,
                        password=self.password,
                        validators=[self.validator] if self.validator else None,
                        classes="input-field",
                        id="input-field"
                    )
                    yield self._input_widget
                
                # 错误消息区域
                yield Static("", classes="error-message", id="error-message")
                
                # 按钮行
                with Center():
                    with Horizontal(classes="input-button-row"):
                        yield Button(
                            self.submit_text, 
                            variant="success", 
                            classes="confirm-button",
                            id="submit-btn"
                        )
                        yield Button(
                            self.cancel_text, 
                            variant="error", 
                            classes="cancel-button",
                            id="cancel-btn"
                        )

    def on_mount(self) -> None:
        """组件挂载时自动聚焦到输入框"""

        # 获取错误组件
        self._error_widget = self.query_one("#error-message", Static)
        
        # 输入组件已经在compose中设置，这里只需要聚焦
        if self._input_widget:
            self._input_widget.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """处理输入变化，实时验证"""
        # 只处理来自我们的输入框的事件
        if event.input.id == "input-field":
            self._clear_error()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理输入框回车提交"""
        # 只处理来自我们的输入框的事件
        if event.input.id == "input-field":
            event.stop()
            self.action_submit()

    @on(Button.Pressed, "#submit-btn")
    def on_submit_pressed(self, event: Button.Pressed) -> None:
        """处理提交按钮点击"""
        event.stop()
        self.action_submit()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self, event: Button.Pressed) -> None:
        """处理取消按钮点击"""
        event.stop()
        self.action_cancel()

    def _validate_input(self) -> bool:
        """验证输入值"""
        if not self._input_widget:
            return False
            
        value = self._input_widget.value.strip()
        
        # 检查必填
        if self.required and not value:
            self._show_error("此字段为必填项")
            return False
        
        # 检查自定义验证器
        if self.validator and value:
            try:
                # 如果有验证器，手动验证
                if hasattr(self.validator, 'validate'):
                    result = self.validator.validate(value)
                    if not result.is_valid:
                        error_msg = "输入格式不正确"
                        if hasattr(result, 'failure_descriptions') and result.failure_descriptions:
                            error_msg = result.failure_descriptions[0]
                        self._show_error(error_msg)
                        return False
            except Exception as e:
                self._show_error(f"验证失败: {str(e)}")
                return False
        
        return True

    def _show_error(self, message: str) -> None:
        """显示错误消息"""
        if self._error_widget:
            self._error_widget.update(message)
            self._error_widget.add_class("visible")

    def _clear_error(self) -> None:
        """清除错误消息"""
        if self._error_widget:
            self._error_widget.remove_class("visible")
            self._error_widget.update("")

    def action_submit(self) -> None:
        """提交操作"""
        if not self._validate_input():
            return
            
        value = self._input_widget.value.strip() if self._input_widget else ""
        
        # 执行回调函数
        if self.submit_callback:
            try:
                self.submit_callback(value)
            except Exception:
                pass
        
        # 发送结果消息
        self.post_message(self.InputResult(submitted=True, value=value, dialog_id=self.dialog_id))
        
        # 关闭对话框并返回结果
        self.dismiss(value)

    def action_cancel(self) -> None:
        """取消操作"""
        # 执行回调函数
        if self.cancel_callback:
            try:
                self.cancel_callback()
            except Exception:
                pass
        
        # 发送结果消息
        self.post_message(self.InputResult(submitted=False, value=None, dialog_id=self.dialog_id))
        
        # 关闭对话框并返回结果
        self.dismiss(None)


# 便利函数，用于快速创建和显示输入对话框
async def show_auto_input_dialog(
    app,
    message: str,
    title: Optional[str] = None,
    placeholder: str = "",
    default_value: str = "",
    input_type: str = "text",
    password: bool = False,
    submit_text: str = "确认",
    cancel_text: str = "取消",
    dialog_id: Optional[str] = None,
    validator: Optional[Validator] = None,
    required: bool = True,
    submit_callback: Optional[Callable[[str], None]] = None,
    cancel_callback: Optional[Callable] = None,
    candidates_callback:  Optional[Callable] = None,
    enable_autocomplete: bool = True,
    ) -> Optional[str]:
    """显示输入对话框并等待用户响应
        
        Args:
            app: Textual应用实例
            message: 提示消息
            title: 对话框标题
            placeholder: 输入框占位符
            default_value: 默认值
            input_type: 输入类型
            password: 是否为密码输入
            submit_text: 提交按钮文本
            cancel_text: 取消按钮文本
            dialog_id: 对话框ID
            validator: 验证器
            required: 是否必填
            submit_callback: 提交回调
            cancel_callback: 取消回调
            candidates_callback: 自动补全回调
            enable_autocomplete: 是否启用自动补全
            
        Returns:
            Optional[str]: 用户输入的值，如果取消则返回None
        """
    def _candidates_callback(state: TargetState) -> list[DropdownItem]:
        if not candidates_callback:
            return []
            
        try:
            candidates = candidates_callback()
            if not candidates:
                return []
            
            # 根据输入过滤股票代码
            filtered = [x for x in candidates if state.text.lower() in x.lower()]
            
            return [
                DropdownItem(x, prefix="")
                for x in filtered
            ]
        except Exception:
            # 如果回调函数出错，返回空列表
            return []
    dialog = WindowInputDialog(
        message=message,
        title=title,
        placeholder=placeholder,
        default_value=default_value,
        input_type=input_type,
        password=password,
        submit_text=submit_text,
        cancel_text=cancel_text,
        dialog_id=dialog_id,
        validator=validator,
        required=required,
        submit_callback=submit_callback,
        cancel_callback=cancel_callback,
        candidates_callback=_candidates_callback,
        enable_autocomplete=enable_autocomplete
    )
    
    result = await app.push_screen_wait(dialog)
    return result
