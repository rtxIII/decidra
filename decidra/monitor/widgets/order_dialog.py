"""
富途交易订单对话框模块

提供下单和改单的可视化界面，基于Textual框架实现。
支持完整的订单参数输入、验证和提交功能。
"""
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any
from ...base.order import *
import re

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Select, Collapsible
from textual.containers import Horizontal, Vertical, Center
from textual.validation import Validator, ValidationResult, Failure

from ...utils.global_vars import get_logger


# 代码前缀 -> 富途交易市场码（HK/US/CN），A股统一为 CN
_MARKET_PREFIX_MAP = {
    "HK": "HK",
    "US": "US",
    "SH": "CN",
    "SZ": "CN",
    "CN": "CN",
}
_DEFAULT_MARKET = "HK"


def infer_market_from_code(code: str) -> str:
    """根据股票代码前缀推断交易市场码

    Args:
        code: 股票代码，如 "HK.00700"、"US.AAPL"、"SH.600000"、"SZ.000001"

    Returns:
        市场码：HK / US / CN；无法识别时回退为 HK
    """
    if not code or "." not in code:
        return _DEFAULT_MARKET
    prefix = code.split(".", 1)[0].strip().upper()
    return _MARKET_PREFIX_MAP.get(prefix, _DEFAULT_MARKET)


# 自定义验证器
class StockCodeValidator(Validator):
    """股票代码验证器"""

    def validate(self, value: str) -> ValidationResult:
        """验证股票代码格式"""
        if not value:
            return ValidationResult(failures=[Failure(self, "股票代码不能为空")])

        # 支持的股票代码格式
        patterns = [
            r'^HK\.\d{5}$',      # 港股：HK.00700
            r'^US\.[A-Z]{1,5}$', # 美股：US.AAPL
            r'^SH\.\d{6}$',      # 沪市：SH.600000
            r'^SZ\.\d{6}$',      # 深市：SZ.000001
        ]

        if not any(re.match(pattern, value.upper()) for pattern in patterns):
            return ValidationResult(failures=[Failure(self, "股票代码格式错误，支持格式：HK.00700, US.AAPL, SH.600000, SZ.000001")])

        return ValidationResult()


class PriceValidator(Validator):
    """价格验证器"""

    def validate(self, value: str) -> ValidationResult:
        """验证价格格式"""
        if not value:
            return ValidationResult(failures=[Failure(self, "价格不能为空")])

        try:
            price = float(value)
            if price <= 0:
                return ValidationResult(failures=[Failure(self, "价格必须大于0")])
            if price > 999999:
                return ValidationResult(failures=[Failure(self, "价格不能超过999999")])
            # 检查小数位数
            if '.' in value:
                decimal_part = value.split('.')[1]
                if decimal_part and len(decimal_part) > 3:
                    return ValidationResult(failures=[Failure(self, "价格最多支持3位小数")])
            return ValidationResult()
        except ValueError:
            return ValidationResult(failures=[Failure(self, "价格必须是数字")])


class OptionalPriceValidator(Validator):
    """可选价格验证器 - 允许空值的价格验证"""

    def validate(self, value: str) -> ValidationResult:
        """验证价格格式，允许空值"""
        if not value or not value.strip():
            return ValidationResult()  # 空值直接通过

        try:
            price = float(value)
            if price <= 0:
                return ValidationResult(failures=[Failure(self, "价格必须大于0")])
            if price > 999999:
                return ValidationResult(failures=[Failure(self, "价格不能超过999999")])
            # 检查小数位数
            if '.' in value:
                decimal_part = value.split('.')[1]
                if decimal_part and len(decimal_part) > 3:
                    return ValidationResult(failures=[Failure(self, "价格最多支持3位小数")])
            return ValidationResult()
        except ValueError:
            return ValidationResult(failures=[Failure(self, "价格必须是数字")])


class QuantityValidator(Validator):
    """数量验证器"""

    def validate(self, value: str) -> ValidationResult:
        """验证数量格式"""
        if not value:
            return ValidationResult(failures=[Failure(self, "数量不能为空")])

        try:
            qty = int(value)
            if qty <= 0:
                return ValidationResult(failures=[Failure(self, "数量必须大于0")])
            if qty > 999999:
                return ValidationResult(failures=[Failure(self, "数量不能超过999999")])
            return ValidationResult()
        except ValueError:
            return ValidationResult(failures=[Failure(self, "数量必须是整数")])


class OptionalQuantityValidator(Validator):
    """可选数量验证器 - 允许空值的数量验证"""

    def validate(self, value: str) -> ValidationResult:
        """验证数量格式，允许空值"""
        from ...utils.global_vars import get_logger
        logger = get_logger(__name__)

        logger.info(f"OptionalQuantityValidator - 输入值: '{value}', 类型: {type(value)}, 长度: {len(value) if value else 0}")

        if not value or not value.strip():
            logger.info("OptionalQuantityValidator - 空值，通过验证")
            return ValidationResult()  # 空值直接通过

        try:
            stripped_value = value.strip()
            logger.info(f"OptionalQuantityValidator - 去空格后: '{stripped_value}'")
            # 先转换为float再转换为int，处理'1100.0'这种情况
            qty = int(float(stripped_value))
            logger.info(f"OptionalQuantityValidator - 转换为整数: {qty}")
            if qty <= 0:
                logger.warning(f"OptionalQuantityValidator - 数量必须大于0: {qty}")
                return ValidationResult(failures=[Failure(self, "数量必须大于0")])
            if qty > 999999:
                logger.warning(f"OptionalQuantityValidator - 数量不能超过999999: {qty}")
                return ValidationResult(failures=[Failure(self, "数量不能超过999999")])
            logger.info(f"OptionalQuantityValidator - 验证通过: {qty}")
            return ValidationResult()
        except ValueError as e:
            logger.warning(f"OptionalQuantityValidator - ValueError: {e}, 值: '{value}'")
            return ValidationResult(failures=[Failure(self, "数量必须是整数")])


class OrderIdValidator(Validator):
    """订单ID验证器"""

    def validate(self, value: str) -> ValidationResult:
        """验证订单ID格式"""
        if not value:
            return ValidationResult(failures=[Failure(self, "订单ID不能为空")])

        if len(value.strip()) < 5:
            return ValidationResult(failures=[Failure(self, "订单ID长度不能少于5位")])

        return ValidationResult()


class PlaceOrderDialog(ModalScreen):
    """下单对话框"""

    DEFAULT_CSS = """
    PlaceOrderDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    .order-dialog-window {
        width: 80;
        height: auto;
        max-height: 45;
        background: $surface;
        border: thick $primary;
        border-title-color: $text;
        border-title-background: $primary;
        border-title-style: bold;
        padding: 1 2;
        margin: 2;
    }

    .order-dialog-content {
        layout: vertical;
        height: auto;
    }

    .order-section {
        layout: vertical;
        height: auto;
        margin-bottom: 1;
        border: solid $secondary;
        padding: 1;
    }

    .order-section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    .order-field-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    .order-field-label {
        width: 12;
        text-align: right;
        padding-right: 1;
        color: $text;
    }

    .order-field-input {
        width: 20;
        margin-right: 2;
    }

    .order-field-select {
        width: 20;
        margin-right: 2;
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

    .order-amount-display {
        height: auto;
        padding: 1 2;
        margin: 1 0;
        background: $panel;
        border: solid $accent;
        text-align: center;
        display: none;
    }

    .order-amount-display.visible {
        display: block;
    }

    .order-amount-display.amount-small {
        color: $success;
    }

    .order-amount-display.amount-medium {
        color: $warning;
    }

    .order-amount-display.amount-large {
        color: rgb(255, 140, 0);  /* 橙色 */
    }

    .order-amount-display.amount-huge {
        color: $error;
    }

    .order-button-row {
        layout: horizontal;
        height: auto;
        align: center middle;
        margin-top: 2;
    }

    .order-button-row Button {
        margin: 0 2;
        min-width: 15;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit_order", "提交订单", priority=True),
        Binding("escape", "cancel_order", "取消", priority=True),
        Binding("ctrl+c", "cancel_order", "取消"),
    ]

    @dataclass
    class OrderResult(Message):
        """订单结果消息"""
        submitted: bool
        order_data: Optional[OrderData] = None
        dialog_id: Optional[str] = None

    def __init__(
        self,
        title: str = "下单",
        default_values: Optional[Dict[str, Any]] = None,
        dialog_id: Optional[str] = None,
        submit_callback: Optional[Callable[[OrderData], None]] = None,
        cancel_callback: Optional[Callable] = None,
    ) -> None:
        """初始化下单对话框

        Args:
            title: 对话框标题
            default_values: 默认值字典
            dialog_id: 对话框唯一标识
            submit_callback: 提交回调函数
            cancel_callback: 取消回调函数
        """
        super().__init__()

        # 初始化logger
        self.logger = get_logger("PlaceOrderDialog")

        self.title = title
        self.default_values = default_values or {}
        self.dialog_id = dialog_id
        self.submit_callback = submit_callback
        self.cancel_callback = cancel_callback

        # 控件引用
        self._code_input: Optional[Input] = None
        self._price_input: Optional[Input] = None
        self._qty_input: Optional[Input] = None
        self._aux_price_input: Optional[Input] = None
        self._remark_input: Optional[Input] = None
        self._order_type_select: Optional[Select] = None
        self._trd_side_select: Optional[Select] = None
        self._trd_env_select: Optional[Select] = None
        self._time_in_force_select: Optional[Select] = None
        self._error_widget: Optional[Static] = None
        self._amount_display: Optional[Static] = None

    def compose(self) -> ComposeResult:
        """构建下单对话框UI"""
        with Vertical(classes="order-dialog-window") as dialog_window:
            dialog_window.border_title = self.title

            with Vertical(classes="order-dialog-content"):
                # 基础信息区域
                with Vertical(classes="order-section") as basic_section:
                    basic_section.border_title = "基础信息"

                    with Horizontal(classes="order-field-row"):
                        yield Static("股票代码:", classes="order-field-label")
                        self._code_input = Input(
                            value=self.default_values.get("code", ""),
                            placeholder="如: HK.00700",
                            validators=[StockCodeValidator()],
                            classes="order-field-input",
                            id="code-input"
                        )
                        yield self._code_input

                        yield Static("交易方向:", classes="order-field-label")
                        self._trd_side_select = Select(
                            options=[(name, code) for code, name in TRD_SIDES],
                            classes="order-field-select",
                            id="trd-side-select"
                        )
                        yield self._trd_side_select

                    with Horizontal(classes="order-field-row"):
                        yield Static("价格:", classes="order-field-label")
                        # 价格默认值：优先使用传入的值，否则为空
                        default_price = self.default_values.get("price", "")
                        self._price_input = Input(
                            value=str(default_price) if default_price else "",
                            placeholder="0.00",
                            validators=[PriceValidator()],
                            classes="order-field-input",
                            id="price-input"
                        )
                        yield self._price_input

                        yield Static("数量:", classes="order-field-label")
                        # 数量默认值：优先使用传入的值，否则默认为100
                        default_qty = self.default_values.get("qty", 100)
                        self._qty_input = Input(
                            value=str(default_qty) if default_qty is not None else "100",
                            placeholder="100",
                            validators=[QuantityValidator()],
                            classes="order-field-input",
                            id="qty-input"
                        )
                        yield self._qty_input

                # 高级选项区域（默认折叠，市场由代码前缀自动推断，不再手选）
                with Collapsible(title="高级选项", collapsed=True, classes="order-advanced"):
                    with Horizontal(classes="order-field-row"):
                        yield Static("订单类型:", classes="order-field-label")
                        self._order_type_select = Select(
                            options=[(name, code) for code, name in ORDER_TYPES],
                            classes="order-field-select",
                            id="order-type-select"
                        )
                        yield self._order_type_select

                        yield Static("交易环境:", classes="order-field-label")
                        self._trd_env_select = Select(
                            options=[(name, code) for code, name in TRD_ENVS],
                            classes="order-field-select",
                            id="trd-env-select"
                        )
                        yield self._trd_env_select

                    with Horizontal(classes="order-field-row"):
                        yield Static("有效期:", classes="order-field-label")
                        self._time_in_force_select = Select(
                            options=[(name, code) for code, name in TIME_IN_FORCE],
                            classes="order-field-select",
                            id="time-in-force-select"
                        )
                        yield self._time_in_force_select

                        yield Static("辅助价格:", classes="order-field-label")
                        self._aux_price_input = Input(
                            value=str(self.default_values.get("aux_price", "")),
                            placeholder="可选",
                            validators=[OptionalPriceValidator()],
                            classes="order-field-input",
                            id="aux-price-input"
                        )
                        yield self._aux_price_input

                    with Horizontal(classes="order-field-row"):
                        yield Static("备注:", classes="order-field-label")
                        self._remark_input = Input(
                            value=self.default_values.get("remark", ""),
                            placeholder="可选",
                            classes="order-field-input",
                            id="remark-input"
                        )
                        yield self._remark_input

                # 错误消息区域
                yield Static("", classes="error-message", id="error-message")

                # 订单总金额显示区域
                yield Static("", classes="order-amount-display", id="order-amount-display")

            # 按钮行（移出order-dialog-content，直接在order-dialog-window下）
            with Center():
                with Horizontal(classes="order-button-row"):
                    yield Button(
                        "提交订单",
                        variant="success",
                        classes="submit-button",
                        id="submit-btn"
                    )
                    yield Button(
                        "取消",
                        variant="error",
                        classes="cancel-button",
                        id="cancel-btn"
                    )

    def on_mount(self) -> None:
        """组件挂载时设置焦点和默认值"""
        self._error_widget = self.query_one("#error-message", Static)
        self._amount_display = self.query_one("#order-amount-display", Static)

        # 设置Select组件的默认值
        # 在options格式为[(name, code)]的情况下，value应该是code
        if self._trd_side_select:
            default_trd_side = self.default_values.get("trd_side", "BUY")
            self._trd_side_select.value = default_trd_side

        if self._order_type_select:
            default_order_type = self.default_values.get("order_type", "NORMAL")
            self._order_type_select.value = default_order_type

        if self._trd_env_select:
            default_trd_env = self.default_values.get("trd_env", "SIMULATE")
            self._trd_env_select.value = default_trd_env

        if self._time_in_force_select:
            default_time_in_force = self.default_values.get("time_in_force", "DAY")
            self._time_in_force_select.value = default_time_in_force

        if self._code_input:
            self._code_input.focus()

        # 初始化订单金额显示
        self._update_order_amount()

    def on_input_changed(self, event: Input.Changed) -> None:
        """处理输入变化，清除错误消息并更新订单金额"""
        self._clear_error()
        # 只在价格或数量输入框变化时更新金额
        if event.input.id in ("price-input", "qty-input"):
            self._update_order_amount()

    @on(Button.Pressed, "#submit-btn")
    def on_submit_pressed(self, event: Button.Pressed) -> None:
        """处理提交按钮点击"""
        event.stop()
        self.action_submit_order()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self, event: Button.Pressed) -> None:
        """处理取消按钮点击"""
        event.stop()
        self.action_cancel_order()

    def _validate_all_inputs(self) -> bool:
        """验证所有输入"""
        self.logger.info("开始验证输入字段...")

        # 验证必填字段
        if not self._code_input or not self._code_input.value.strip():
            self.logger.warning("股票代码验证失败 - 空值")
            self._show_error("股票代码不能为空")
            return False

        if not self._price_input or not self._price_input.value.strip():
            self.logger.warning("价格验证失败 - 空值")
            self._show_error("价格不能为空")
            return False

        if not self._qty_input or not self._qty_input.value.strip():
            self.logger.warning("数量验证失败 - 空值")
            self._show_error("数量不能为空")
            return False

        self.logger.info(f"必填字段检查通过 - 代码: '{self._code_input.value}', 价格: '{self._price_input.value}', 数量: '{self._qty_input.value}'")

        # 验证各个字段格式
        validators = [
            (self._code_input, StockCodeValidator(), "股票代码"),
            (self._price_input, PriceValidator(), "价格"),
            (self._qty_input, QuantityValidator(), "数量"),
        ]

        # 如果辅助价格不为空，也需要验证
        if self._aux_price_input and self._aux_price_input.value.strip():
            validators.append((self._aux_price_input, OptionalPriceValidator(), "辅助价格"))

        for input_widget, validator, field_name in validators:
            if input_widget and input_widget.value.strip():
                result = validator.validate(input_widget.value.strip())
                if not result.is_valid:
                    error_msg = result.failure_descriptions[0] if result.failure_descriptions else "格式错误"
                    self.logger.info(f"{field_name}验证失败 - 值: '{input_widget.value}', 错误: {error_msg}")
                    self._show_error(error_msg)
                    input_widget.focus()
                    return False
                else:
                    self.logger.info(f"{field_name}验证成功 - 值: '{input_widget.value}'")

        self.logger.info("所有输入验证通过")
        return True

    def _collect_order_data(self) -> OrderData:
        """收集订单数据

        Raises:
            ValueError: 当数据类型转换失败时
        """
        # 转换价格和数量，添加显式错误处理
        try:
            price = float(self._price_input.value.strip())
        except ValueError as e:
            self.logger.error(f"价格数据类型转换失败: {e}")
            raise ValueError(f"价格数据格式错误: {e}") from e

        try:
            qty = int(self._qty_input.value.strip())
        except ValueError as e:
            self.logger.error(f"数量数据类型转换失败: {e}")
            raise ValueError(f"数量数据格式错误: {e}") from e

        # 转换辅助价格（可选）
        aux_price = None
        if self._aux_price_input and self._aux_price_input.value.strip():
            try:
                aux_price = float(self._aux_price_input.value.strip())
            except ValueError as e:
                self.logger.warning(f"辅助价格转换失败，将设置为None: {e}")
                aux_price = None

        # 获取Select组件的值，提供默认值防止None
        order_type = self._order_type_select.value if self._order_type_select.value is not None else "NORMAL"
        trd_side = self._trd_side_select.value if self._trd_side_select.value is not None else "BUY"
        trd_env = self._trd_env_select.value if self._trd_env_select.value is not None else "SIMULATE"
        time_in_force = self._time_in_force_select.value if self._time_in_force_select.value is not None else "DAY"

        # 市场由代码前缀自动推断，避免用户手选出错
        code = self._code_input.value.strip().upper()
        market = infer_market_from_code(code)

        self.logger.info(f"Select组件值 - order_type: {order_type}, trd_side: {trd_side}, trd_env: {trd_env}, market: {market}(推断), time_in_force: {time_in_force}")

        return OrderData(
            code=code,
            price=price,
            qty=qty,
            order_type=order_type,
            trd_side=trd_side,
            trd_env=trd_env,
            market=market,
            aux_price=aux_price,
            time_in_force=time_in_force,
            remark=self._remark_input.value.strip() if self._remark_input else ""
        )

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

    def _update_order_amount(self) -> None:
        """更新订单总金额显示"""
        if not self._amount_display:
            return

        # 尝试获取价格和数量
        try:
            price_str = self._price_input.value.strip() if self._price_input else ""
            qty_str = self._qty_input.value.strip() if self._qty_input else ""

            # 如果价格或数量为空，隐藏金额显示
            if not price_str or not qty_str:
                self._amount_display.remove_class("visible")
                return

            # 转换为数值
            price = float(price_str)
            qty = int(qty_str)

            # 计算总金额
            total_amount = price * qty

            # 格式化显示金额（千分位分隔符）
            amount_str = f"{total_amount:,.2f}"

            # 根据金额大小选择颜色类
            # 移除旧的颜色类
            self._amount_display.remove_class("amount-small")
            self._amount_display.remove_class("amount-medium")
            self._amount_display.remove_class("amount-large")
            self._amount_display.remove_class("amount-huge")

            # 添加新的颜色类
            if total_amount < 100000:  # < 10万
                self._amount_display.add_class("amount-small")
                level = "较小"
            elif total_amount < 500000:  # 10万 - 50万
                self._amount_display.add_class("amount-medium")
                level = "中等"
            elif total_amount < 1000000:  # 50万 - 100万
                self._amount_display.add_class("amount-large")
                level = "较大"
            else:  # > 100万
                self._amount_display.add_class("amount-huge")
                level = "很大"

            # 更新显示文本
            display_text = f"订单总金额: ¥{amount_str} (价格 {price} × 数量 {qty}) [{level}]"
            self._amount_display.update(display_text)
            self._amount_display.add_class("visible")

        except (ValueError, TypeError):
            # 输入不是有效数字时隐藏显示
            self._amount_display.remove_class("visible")

    def action_submit_order(self) -> None:
        """提交订单操作"""
        # 添加调试信息
        self.logger.info("开始验证订单输入...")

        if not self._validate_all_inputs():
            self.logger.info("验证失败，订单提交中止")
            return

        self.logger.info("验证成功，开始收集订单数据...")

        try:
            order_data = self._collect_order_data()
            self.logger.info(f"订单数据收集成功: {order_data}")
        except Exception as e:
            self.logger.error(f"订单数据收集失败: {e}")
            self._show_error(f"数据收集失败: {str(e)}")
            return

        # 执行回调函数
        if self.submit_callback:
            try:
                self.submit_callback(order_data)
                self.logger.info("回调函数执行成功")
            except Exception as e:
                self.logger.error(f"回调函数执行失败: {e}")

        # 发送结果消息
        self.post_message(self.OrderResult(submitted=True, order_data=order_data, dialog_id=self.dialog_id))

        # 关闭对话框
        self.logger.info("关闭对话框，返回订单数据")
        self.dismiss(order_data)

    def action_cancel_order(self) -> None:
        """取消操作"""
        # 执行回调函数
        if self.cancel_callback:
            try:
                self.cancel_callback()
            except Exception:
                pass

        # 发送结果消息
        self.post_message(self.OrderResult(submitted=False, order_data=None, dialog_id=self.dialog_id))

        # 关闭对话框
        self.dismiss(None)


class ModifyOrderDialog(ModalScreen):
    """改单对话框"""

    DEFAULT_CSS = """
    ModifyOrderDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    .modify-order-window {
        width: 60;
        height: auto;
        max-height: 30;
        background: $surface;
        border: thick $primary;
        border-title-color: $text;
        border-title-background: $primary;
        border-title-style: bold;
        padding: 1 2;
        margin: 2;
    }

    .modify-order-content {
        layout: vertical;
        height: auto;
    }

    .modify-field-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    .modify-field-label {
        width: 12;
        text-align: right;
        padding-right: 1;
        color: $text;
    }

    .modify-field-input {
        width: 25;
        margin-right: 2;
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

    .order-amount-display {
        height: auto;
        padding: 1 2;
        margin: 1 0;
        background: $panel;
        border: solid $accent;
        text-align: center;
        display: none;
    }

    .order-amount-display.visible {
        display: block;
    }

    .order-amount-display.amount-small {
        color: $success;
    }

    .order-amount-display.amount-medium {
        color: $warning;
    }

    .order-amount-display.amount-large {
        color: rgb(255, 140, 0);  /* 橙色 */
    }

    .order-amount-display.amount-huge {
        color: $error;
    }

    .modify-button-row {
        layout: horizontal;
        height: auto;
        align: center middle;
        margin-top: 2;
    }

    .modify-button-row Button {
        margin: 0 2;
        min-width: 15;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit_modify", "提交修改", priority=True),
        Binding("escape", "cancel_modify", "取消", priority=True),
        Binding("ctrl+c", "cancel_modify", "取消"),
    ]

    @dataclass
    class ModifyResult(Message):
        """改单结果消息"""
        submitted: bool
        modify_data: Optional[ModifyOrderData] = None
        dialog_id: Optional[str] = None

    def __init__(
        self,
        title: str = "修改订单",
        order_id: str = "",
        current_price: Optional[float] = None,
        current_qty: Optional[int] = None,
        dialog_id: Optional[str] = None,
        submit_callback: Optional[Callable[[ModifyOrderData], None]] = None,
        cancel_callback: Optional[Callable] = None,
    ) -> None:
        """初始化改单对话框

        Args:
            title: 对话框标题
            order_id: 订单ID
            current_price: 当前价格
            current_qty: 当前数量
            dialog_id: 对话框唯一标识
            submit_callback: 提交回调函数
            cancel_callback: 取消回调函数
        """
        super().__init__()

        # 初始化logger
        self.logger = get_logger("ModifyOrderDialog")

        self.title = title
        self.order_id = order_id
        self.current_price = current_price
        self.current_qty = current_qty
        self.dialog_id = dialog_id
        self.submit_callback = submit_callback
        self.cancel_callback = cancel_callback

        # 控件引用
        self._order_id_input: Optional[Input] = None
        self._new_price_input: Optional[Input] = None
        self._new_qty_input: Optional[Input] = None
        self._aux_price_input: Optional[Input] = None
        self._error_widget: Optional[Static] = None
        self._amount_display: Optional[Static] = None

    def compose(self) -> ComposeResult:
        """构建改单对话框UI"""
        with Vertical(classes="modify-order-window") as dialog_window:
            dialog_window.border_title = self.title

            with Vertical(classes="modify-order-content"):
                # 订单ID输入
                with Horizontal(classes="modify-field-row"):
                    yield Static("订单ID:", classes="modify-field-label")
                    self._order_id_input = Input(
                        value=self.order_id,
                        placeholder="订单唯一标识",
                        validators=[OrderIdValidator()],
                        classes="modify-field-input",
                        id="order-id-input"
                    )
                    yield self._order_id_input

                # 新价格输入
                with Horizontal(classes="modify-field-row"):
                    yield Static("新价格:", classes="modify-field-label")
                    self._new_price_input = Input(
                        value=str(self.current_price) if self.current_price else "",
                        placeholder="留空则不修改",
                        validators=[OptionalPriceValidator()],
                        classes="modify-field-input",
                        id="new-price-input"
                    )
                    yield self._new_price_input

                # 新数量输入
                with Horizontal(classes="modify-field-row"):
                    yield Static("新数量:", classes="modify-field-label")
                    # 确保数量显示为整数格式，处理可能的浮点数
                    qty_display = ""
                    if self.current_qty is not None:
                        try:
                            qty_display = str(int(float(self.current_qty)))
                        except (ValueError, TypeError):
                            qty_display = str(self.current_qty)
                    self._new_qty_input = Input(
                        value=qty_display,
                        placeholder="留空则不修改",
                        validators=[OptionalQuantityValidator()],
                        classes="modify-field-input",
                        id="new-qty-input"
                    )
                    yield self._new_qty_input

                # 新辅助价格输入
                with Horizontal(classes="modify-field-row"):
                    yield Static("新辅助价格:", classes="modify-field-label")
                    self._aux_price_input = Input(
                        value="",
                        placeholder="可选",
                        validators=[OptionalPriceValidator()],
                        classes="modify-field-input",
                        id="new-aux-price-input"
                    )
                    yield self._aux_price_input

                # 错误消息区域
                yield Static("", classes="error-message", id="error-message")

                # 订单总金额显示区域
                yield Static("", classes="order-amount-display", id="order-amount-display")

            # 按钮行（移出modify-order-content，直接在modify-order-window下）
            with Center():
                with Horizontal(classes="modify-button-row"):
                    yield Button(
                        "提交修改",
                        variant="success",
                        classes="submit-button",
                        id="submit-btn"
                    )
                    yield Button(
                        "取消",
                        variant="error",
                        classes="cancel-button",
                        id="cancel-btn"
                    )

    def on_mount(self) -> None:
        """组件挂载时设置焦点"""
        self._error_widget = self.query_one("#error-message", Static)
        self._amount_display = self.query_one("#order-amount-display", Static)

        if self._order_id_input:
            self._order_id_input.focus()

        # 初始化订单金额显示
        self._update_order_amount()

    def on_input_changed(self, event: Input.Changed) -> None:
        """处理输入变化，清除错误消息并更新订单金额"""
        self._clear_error()
        # 只在价格或数量输入框变化时更新金额
        if event.input.id in ("new-price-input", "new-qty-input"):
            self._update_order_amount()

    @on(Button.Pressed, "#submit-btn")
    def on_submit_pressed(self, event: Button.Pressed) -> None:
        """处理提交按钮点击"""
        event.stop()
        self.action_submit_modify()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self, event: Button.Pressed) -> None:
        """处理取消按钮点击"""
        event.stop()
        self.action_cancel_modify()

    def _validate_inputs(self) -> bool:
        """验证输入"""
        self.logger.info("开始验证改单输入字段...")

        # 订单ID必填
        if not self._order_id_input or not self._order_id_input.value.strip():
            self.logger.warning("订单ID验证失败 - 空值")
            self._show_error("订单ID不能为空")
            return False

        # 验证订单ID格式
        order_id_validator = OrderIdValidator()
        result = order_id_validator.validate(self._order_id_input.value.strip())
        if not result.is_valid:
            error_msg = result.failure_descriptions[0] if result.failure_descriptions else "订单ID格式错误"
            self.logger.warning(f"订单ID验证失败 - {error_msg}")
            self._show_error(error_msg)
            return False

        self.logger.info(f"订单ID验证成功 - 值: '{self._order_id_input.value}'")

        # 价格和数量至少要有一个
        has_price = self._new_price_input and self._new_price_input.value.strip()
        has_qty = self._new_qty_input and self._new_qty_input.value.strip()

        if not has_price and not has_qty:
            self.logger.warning("验证失败 - 价格和数量都为空")
            self._show_error("新价格和新数量至少要填写一个")
            return False

        # 验证价格格式（如果填写）
        if has_price:
            price_validator = OptionalPriceValidator()
            result = price_validator.validate(self._new_price_input.value.strip())
            if not result.is_valid:
                error_msg = result.failure_descriptions[0] if result.failure_descriptions else "价格格式错误"
                self.logger.warning(f"新价格验证失败 - {error_msg}")
                self._show_error(error_msg)
                return False
            self.logger.info(f"新价格验证成功 - 值: '{self._new_price_input.value}'")

        # 验证数量格式（如果填写）
        if has_qty:
            qty_value = self._new_qty_input.value.strip()
            self.logger.info(f"开始验证数量 - 原始值: '{self._new_qty_input.value}', 去空格后: '{qty_value}', 长度: {len(qty_value)}, 字符: {[ord(c) for c in qty_value]}")
            qty_validator = OptionalQuantityValidator()
            result = qty_validator.validate(qty_value)
            if not result.is_valid:
                error_msg = result.failure_descriptions[0] if result.failure_descriptions else "数量格式错误"
                self.logger.warning(f"新数量验证失败 - {error_msg}")
                self._show_error(error_msg)
                return False
            self.logger.info(f"新数量验证成功 - 值: '{qty_value}'")

        # 验证辅助价格格式（如果填写）
        if self._aux_price_input and self._aux_price_input.value.strip():
            aux_price_validator = OptionalPriceValidator()
            result = aux_price_validator.validate(self._aux_price_input.value.strip())
            if not result.is_valid:
                error_msg = result.failure_descriptions[0] if result.failure_descriptions else "辅助价格格式错误"
                self.logger.warning(f"辅助价格验证失败 - {error_msg}")
                self._show_error(error_msg)
                return False
            self.logger.info(f"辅助价格验证成功 - 值: '{self._aux_price_input.value}'")

        self.logger.info("所有输入验证通过")
        return True

    def _collect_modify_data(self) -> ModifyOrderData:
        """收集改单数据

        Raises:
            ValueError: 当数据类型转换失败时
        """
        # 转换新价格（可选，但如果填写了必须有效）
        new_price = None
        if self._new_price_input and self._new_price_input.value.strip():
            try:
                new_price = float(self._new_price_input.value.strip())
            except ValueError as e:
                self.logger.error(f"新价格数据类型转换失败: {e}")
                raise ValueError(f"新价格数据格式错误: {e}") from e

        # 转换新数量（可选，但如果填写了必须有效）
        new_qty = None
        if self._new_qty_input and self._new_qty_input.value.strip():
            try:
                new_qty = int(self._new_qty_input.value.strip())
            except ValueError as e:
                self.logger.error(f"新数量数据类型转换失败: {e}")
                raise ValueError(f"新数量数据格式错误: {e}") from e

        # 转换辅助价格（可选）
        aux_price = None
        if self._aux_price_input and self._aux_price_input.value.strip():
            try:
                aux_price = float(self._aux_price_input.value.strip())
            except ValueError as e:
                self.logger.warning(f"辅助价格转换失败，将设置为None: {e}")
                aux_price = None

        return ModifyOrderData(
            order_id=self._order_id_input.value.strip(),
            price=new_price,
            qty=new_qty,
            aux_price=aux_price
        )

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

    def _update_order_amount(self) -> None:
        """更新订单总金额显示（改单对话框）"""
        if not self._amount_display:
            return

        # 尝试获取新价格和新数量
        try:
            new_price_str = self._new_price_input.value.strip() if self._new_price_input else ""
            new_qty_str = self._new_qty_input.value.strip() if self._new_qty_input else ""

            # 使用当前值或新值
            price = None
            qty = None

            if new_price_str:
                price = float(new_price_str)
            elif self.current_price is not None:
                price = self.current_price

            if new_qty_str:
                qty = int(float(new_qty_str))  # 处理'1100.0'这种情况
            elif self.current_qty is not None:
                qty = int(self.current_qty)

            # 如果价格或数量仍然为空，隐藏金额显示
            if price is None or qty is None:
                self._amount_display.remove_class("visible")
                return

            # 计算当前总金额和新总金额
            current_amount = None
            if self.current_price is not None and self.current_qty is not None:
                current_amount = self.current_price * self.current_qty

            new_amount = price * qty

            # 格式化显示金额（千分位分隔符）
            new_amount_str = f"{new_amount:,.2f}"

            # 根据金额大小选择颜色类
            # 移除旧的颜色类
            self._amount_display.remove_class("amount-small")
            self._amount_display.remove_class("amount-medium")
            self._amount_display.remove_class("amount-large")
            self._amount_display.remove_class("amount-huge")

            # 添加新的颜色类
            if new_amount < 100000:  # < 10万
                self._amount_display.add_class("amount-small")
                level = "较小"
            elif new_amount < 500000:  # 10万 - 50万
                self._amount_display.add_class("amount-medium")
                level = "中等"
            elif new_amount < 1000000:  # 50万 - 100万
                self._amount_display.add_class("amount-large")
                level = "较大"
            else:  # > 100万
                self._amount_display.add_class("amount-huge")
                level = "很大"

            # 更新显示文本
            if current_amount is not None and abs(new_amount - current_amount) > 0.01:
                # 显示对比信息
                current_amount_str = f"{current_amount:,.2f}"
                diff = new_amount - current_amount
                diff_str = f"{diff:+,.2f}"
                display_text = f"¥{new_amount_str} (原: ¥{current_amount_str}, 差额: {diff_str})"
            else:
                # 只显示新金额
                display_text = f"¥{new_amount_str} (价格 {price} × 数量 {qty})"

            self._amount_display.update(display_text)
            self._amount_display.add_class("visible")

        except (ValueError, TypeError):
            # 输入不是有效数字时隐藏显示
            self._amount_display.remove_class("visible")

    def action_submit_modify(self) -> None:
        """提交修改操作"""
        self.logger.info("开始验证改单输入...")

        if not self._validate_inputs():
            self.logger.info("验证失败，改单提交中止")
            return

        self.logger.info("验证成功，开始收集改单数据...")

        try:
            modify_data = self._collect_modify_data()
            self.logger.info(f"改单数据收集成功: {modify_data}")
        except Exception as e:
            self.logger.error(f"改单数据收集失败: {e}")
            self._show_error(f"数据收集失败: {str(e)}")
            return

        # 执行回调函数
        if self.submit_callback:
            try:
                self.submit_callback(modify_data)
                self.logger.info("回调函数执行成功")
            except Exception as e:
                self.logger.error(f"回调函数执行失败: {e}", exc_info=True)

        # 发送结果消息
        self.post_message(self.ModifyResult(submitted=True, modify_data=modify_data, dialog_id=self.dialog_id))

        # 关闭对话框
        self.logger.info("关闭对话框，返回改单数据")
        self.dismiss(modify_data)

    def action_cancel_modify(self) -> None:
        """取消操作"""
        # 执行回调函数
        if self.cancel_callback:
            try:
                self.cancel_callback()
            except Exception:
                pass

        # 发送结果消息
        self.post_message(self.ModifyResult(submitted=False, modify_data=None, dialog_id=self.dialog_id))

        # 关闭对话框
        self.dismiss(None)


# 便利函数
async def show_place_order_dialog(
    app,
    title: str = "下单",
    default_values: Optional[Dict[str, Any]] = None,
    dialog_id: Optional[str] = None,
    submit_callback: Optional[Callable[[OrderData], None]] = None,
    cancel_callback: Optional[Callable] = None,
) -> Optional[OrderData]:
    """显示下单对话框并等待用户响应

    Args:
        app: Textual应用实例
        title: 对话框标题
        default_values: 默认值字典
        dialog_id: 对话框ID
        submit_callback: 提交回调
        cancel_callback: 取消回调

    Returns:
        Optional[OrderData]: 用户输入的订单数据，如果取消则返回None
    """
    dialog = PlaceOrderDialog(
        title=title,
        default_values=default_values,
        dialog_id=dialog_id,
        submit_callback=submit_callback,
        cancel_callback=cancel_callback
    )

    result = await app.push_screen_wait(dialog)
    return result


async def show_modify_order_dialog(
    app,
    title: str = "修改订单",
    order_id: str = "",
    current_price: Optional[float] = None,
    current_qty: Optional[int] = None,
    dialog_id: Optional[str] = None,
    submit_callback: Optional[Callable[[ModifyOrderData], None]] = None,
    cancel_callback: Optional[Callable] = None,
) -> Optional[ModifyOrderData]:
    """显示改单对话框并等待用户响应

    Args:
        app: Textual应用实例
        title: 对话框标题
        order_id: 订单ID
        current_price: 当前价格
        current_qty: 当前数量
        dialog_id: 对话框ID
        submit_callback: 提交回调
        cancel_callback: 取消回调

    Returns:
        Optional[ModifyOrderData]: 用户输入的改单数据，如果取消则返回None
    """
    dialog = ModifyOrderDialog(
        title=title,
        order_id=order_id,
        current_price=current_price,
        current_qty=current_qty,
        dialog_id=dialog_id,
        submit_callback=submit_callback,
        cancel_callback=cancel_callback
    )

    result = await app.push_screen_wait(dialog)
    return result