"""
专业信息输出框架
适用于金融监控应用的多功能信息显示组件

主要功能:
- 多种信息类型支持 (日志、股票数据、交易信息、性能指标等)
- 分级显示系统 (ERROR、WARNING、INFO、DEBUG)
- 实时滚动更新和缓冲区管理
- 过滤和搜索功能
- 与项目logger系统集成
- 专业的金融数据显示样式
"""

from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass
from collections import deque

from rich.json import JSON
from rich.text import Text

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label, Static, Input, Button, Select
from textual.reactive import reactive
from textual.message import Message

from ...utils.global_vars import get_logger

# 导入AI相关模块
try:
    from ...modules.ai.claude_ai_client import create_claude_client, TradingAdvice, TradingOrder
    from ...monitor.widgets.window_dialog import WindowInputDialog
    from ...monitor.widgets.thinking_animation import ThinkingAnimation
    from ...monitor.widgets.order_dialog import PlaceOrderDialog, OrderData
    from ...monitor.widgets.ai_quick_dialog import AIDialogResult
    from ...base.ai import AIAnalysisRequest, AITradingAdviceRequest
    AI_MODULES_AVAILABLE = True
except ImportError:
    create_claude_client = None
    TradingAdvice = None
    TradingOrder = None
    WindowInputDialog = None
    ThinkingAnimation = None
    PlaceOrderDialog = None
    OrderData = None
    AIDialogResult = None
    AIAnalysisRequest = None
    AITradingAdviceRequest = None
    AI_MODULES_AVAILABLE = False


class InfoType(Enum):
    """信息类型枚举"""
    LOG = "log"                    # 系统日志
    STOCK_DATA = "stock_data"      # 股票数据
    TRADE_INFO = "trade_info"      # 交易信息
    TRADE_ADVICE = "trade_advice"  # AI交易建议
    PERFORMANCE = "performance"    # 性能指标
    API_STATUS = "api_status"      # API状态
    USER_ACTION = "user_action"    # 用户操作
    ERROR = "error"                # 错误信息
    WARNING = "warning"            # 警告信息


class InfoLevel(Enum):
    """信息级别枚举"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class InfoMessage:
    """信息消息数据类"""
    content: str
    info_type: InfoType
    level: InfoLevel
    timestamp: datetime
    source: str = ""
    data: Optional[Dict[str, Any]] = None
    formatted_text: Optional[Text] = None
    
    def __post_init__(self):
        """初始化后处理"""
        if self.formatted_text is None:
            self.formatted_text = self._format_message()
    
    def _format_message(self) -> Text:
        """格式化消息文本"""
        # 时间戳格式化
        time_str = self.timestamp.strftime("%H:%M:%S")
        
        # 根据信息类型和级别选择颜色和图标
        color, icon = self._get_style()
        
        # 构建格式化文本
        text = Text()
        text.append(f"[{time_str}] ", style="dim")
        text.append(f"{icon} ", style=color)
        text.append(f"[{self.info_type.value.upper()}] ", style=f"bold {color}")
        text.append(self.content, style=color if self.level in [InfoLevel.ERROR, InfoLevel.WARNING] else "default")
        
        if self.source:
            text.append(f" ({self.source})", style="dim")
        
        return text
    
    def _get_style(self) -> tuple[str, str]:
        """获取样式和图标"""
        style_map = {
            InfoLevel.DEBUG: ("blue", "🔍"),
            InfoLevel.INFO: ("green", "ℹ️"),
            InfoLevel.WARNING: ("yellow", "⚠️"),
            InfoLevel.ERROR: ("red", "❌"),
            InfoLevel.CRITICAL: ("bold red", "🚨"),
        }
        
        # 根据信息类型调整样式
        type_icons = {
            InfoType.STOCK_DATA: "📈",
            InfoType.TRADE_INFO: "💰",
            InfoType.PERFORMANCE: "⚡",
            InfoType.API_STATUS: "🔗",
            InfoType.USER_ACTION: "👤",
        }
        
        color, _ = style_map.get(self.level, ("default", "•"))
        icon = type_icons.get(self.info_type, style_map.get(self.level, ("default", "•"))[1])
        
        return color, icon


class InfoBuffer:
    """信息缓冲区管理器"""
    
    def __init__(self, max_size: int = 1000):
        """
        初始化缓冲区
        
        Args:
            max_size: 最大存储消息数量
        """
        self.max_size = max_size
        self.messages: deque[InfoMessage] = deque(maxlen=max_size)
        self.filters: Dict[str, Callable[[InfoMessage], bool]] = {}
        self.logger = get_logger(__name__)
    
    def add_message(self, message: InfoMessage) -> None:
        """添加新消息"""
        self.messages.append(message)
        self.logger.debug(f"Added message: {message.info_type.value} - {message.content[:50]}...")
    
    def get_filtered_messages(self, 
                            info_types: Optional[List[InfoType]] = None,
                            levels: Optional[List[InfoLevel]] = None,
                            time_range: Optional[tuple[datetime, datetime]] = None,
                            search_text: Optional[str] = None) -> List[InfoMessage]:
        """
        获取过滤后的消息列表
        
        Args:
            info_types: 信息类型过滤
            levels: 级别过滤
            time_range: 时间范围过滤 (start, end)
            search_text: 搜索文本
        """
        filtered = list(self.messages)
        
        # 类型过滤
        if info_types:
            filtered = [msg for msg in filtered if msg.info_type in info_types]
        
        # 级别过滤
        if levels:
            filtered = [msg for msg in filtered if msg.level in levels]
        
        # 时间范围过滤
        if time_range:
            start_time, end_time = time_range
            filtered = [msg for msg in filtered if start_time <= msg.timestamp <= end_time]
        
        # 文本搜索
        if search_text:
            search_lower = search_text.lower()
            filtered = [msg for msg in filtered 
                       if search_lower in msg.content.lower() or 
                          search_lower in msg.source.lower()]
        
        return filtered
    
    def clear(self) -> None:
        """清空缓冲区"""
        self.messages.clear()
        self.logger.info("Info buffer cleared")

    def remove_message_by_advice_id(self, advice_id: str) -> bool:
        """根据建议ID删除消息

        Args:
            advice_id: 交易建议ID

        Returns:
            bool: 是否成功删除消息
        """
        messages_to_remove = []
        for msg in self.messages:
            if msg.data and msg.data.get('advice_id') == advice_id:
                messages_to_remove.append(msg)

        if messages_to_remove:
            for msg in messages_to_remove:
                self.messages.remove(msg)
            self.logger.info(f"Removed {len(messages_to_remove)} message(s) with advice_id: {advice_id[:8]}")
            return True

        self.logger.warning(f"No message found with advice_id: {advice_id[:8]}")
        return False

    def get_stats(self) -> Dict[str, int]:
        """获取缓冲区统计信息"""
        stats = {
            "total": len(self.messages),
            "by_type": {},
            "by_level": {}
        }
        
        for msg in self.messages:
            # 按类型统计
            type_name = msg.info_type.value
            stats["by_type"][type_name] = stats["by_type"].get(type_name, 0) + 1
            
            # 按级别统计
            level_name = msg.level.value
            stats["by_level"][level_name] = stats["by_level"].get(level_name, 0) + 1
        
        return stats


class InfoDisplay(Widget):
    """单条信息显示组件"""
    
    DEFAULT_CSS = """
    InfoDisplay {
        height: auto;
        width: 1fr;
        padding: 0 1;
        margin: 0;
    }
    
    InfoDisplay Label {
        width: 1fr;
        height: auto;
    }
    
    InfoDisplay.error {
        background: rgba(255, 0, 0, 0.1);
        border-left: thick $error;
    }
    
    InfoDisplay.warning {
        background: rgba(255, 255, 0, 0.1);
        border-left: thick $warning;
    }
    
    InfoDisplay.info {
        border-left: thick $primary;
    }
    
    InfoDisplay.debug {
        opacity: 0.7;
        border-left: thick $text-muted;
    }
    
    InfoDisplay.stock-data {
        background: rgba(0, 255, 0, 0.05);
        border-left: thick $success;
    }
    
    InfoDisplay.trade-info {
        background: rgba(255, 215, 0, 0.1);
        border-left: thick $secondary;
    }
    """
    
    def __init__(self, message: InfoMessage, **kwargs):
        """初始化信息显示组件"""
        super().__init__(**kwargs)
        self.message = message
        
        # 设置CSS类
        self.add_class(message.level.value)
        self.add_class(message.info_type.value.replace("_", "-"))
    
    def compose(self) -> ComposeResult:
        """组合组件"""
        # 处理JSON数据
        if self.message.data and self.message.info_type == InfoType.STOCK_DATA:
            try:
                yield Static(JSON.from_data(self.message.data), expand=True)
                return
            except Exception:
                pass
        
        # 处理多行文本
        if isinstance(self.message.formatted_text, Text):
            yield Label(self.message.formatted_text)
        else:
            yield Label(self.message.content)


class InfoFilterBar(Horizontal):
    """信息过滤工具栏"""
    
    DEFAULT_CSS = """
    InfoFilterBar {
        height: 3;
        dock: top;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $border;
    }
    
    InfoFilterBar Input {
        width: 1fr;
        margin-right: 1;
    }
    
    InfoFilterBar Select {
        width: 15;
        margin-right: 1;
    }
    
    InfoFilterBar Button {
        width: 8;
        margin-right: 1;
    }
    
    InfoFilterBar #ai_button {
        width: 8;
        margin-right: 1;
        background: $primary;
        color: $text;
    }
    
    InfoFilterBar #ai_button:hover {
        background: $primary-lighten-2;
    }
    """
    
    class FilterChanged(Message):
        """过滤条件改变消息"""
        def __init__(self, filters: Dict[str, Any]):
            super().__init__()
            self.filters = filters
    
    def __init__(self, **kwargs):
        """初始化过滤工具栏"""
        super().__init__(**kwargs)
        self.current_filters = {}
    
    def compose(self) -> ComposeResult:
        """组合过滤工具栏"""
        # 搜索输入框
        yield Input(placeholder="搜索信息...", id="search_input")
        
        # AI交互按钮
        if AI_MODULES_AVAILABLE:
            yield Button("💻 AI", id="ai_button", variant="primary")
        
        # 类型选择器 - 提供中文标签
        type_labels = {
            "log": "系统日志",
            "stock_data": "股票数据",
            "trade_info": "交易信息",
            "trade_advice": "AI交易建议",
            "performance": "性能指标",
            "api_status": "API状态",
            "user_action": "用户操作",
            "error": "错误信息",
            "warning": "警告信息"
        }
        type_options = [("全部", "all")] + [(type_labels.get(t.value, t.value), t.value) for t in InfoType]
        yield Select(type_options, value="all", id="type_select")

        # 级别选择器 - 提供中文标签
        level_labels = {
            "debug": "调试",
            "info": "信息",
            "warning": "警告",
            "error": "错误",
            "critical": "严重"
        }
        level_options = [("全部", "all")] + [(level_labels.get(l.value, l.value), l.value) for l in InfoLevel]
        yield Select(level_options, value="all", id="level_select")
        
        # 清空按钮
        yield Button("清空", id="clear_button")
    
    async def on_input_changed(self, event: Input.Changed) -> None:
        """搜索框内容改变"""
        if event.input.id == "search_input":
            self.current_filters["search"] = event.value
            self.post_message(self.FilterChanged(self.current_filters))
    
    async def on_select_changed(self, event: Select.Changed) -> None:
        """选择器改变"""
        if event.select.id == "type_select":
            self.current_filters["type"] = event.value if event.value != "all" else None
        elif event.select.id == "level_select":
            self.current_filters["level"] = event.value if event.value != "all" else None
        
        self.post_message(self.FilterChanged(self.current_filters))
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击"""
        if event.button.id == "clear_button":
            self.current_filters["clear"] = True
            self.post_message(self.FilterChanged(self.current_filters))
        elif event.button.id == "ai_button":
            await self._handle_ai_interaction()
    
    async def _handle_ai_interaction(self) -> None:
        """处理AI交互"""
        if not AI_MODULES_AVAILABLE:
            # 如果AI模块不可用，发送错误消息
            self.current_filters["ai_error"] = "AI功能不可用，请检查相关模块安装。"
            self.post_message(self.FilterChanged(self.current_filters))
            return
        
        # 发送AI交互请求，由InfoPanel处理具体的对话框显示和AI调用
        self.current_filters["show_ai_dialog"] = True
        self.post_message(self.FilterChanged(self.current_filters))


class InfoPanel(Widget):
    """专业信息面板组件 - 参考toolong双面板设计"""

    DEFAULT_CSS = """
    InfoPanel {
        layout: horizontal;
        background: $panel;
        border: solid $border;
        border-title-color: $text;
        border-title-background: $surface;
        height: 1fr;
        width: 1fr;
    }

    InfoPanel:focus {
        border: heavy $accent;
    }

    InfoPanel .left-panel {
        width: 1fr;  /* 50% */
        height: 1fr;
        background: $surface;
        border-right: solid $border;
    }

    InfoPanel .right-panel {
        width: 1fr;  /* 50% */
        height: 1fr;
        background: $panel;
    }

    InfoPanel .panel-title {
        height: 1;
        dock: top;
        background: $primary;
        color: $text;
        text-align: center;
        text-style: bold;
    }
    """
    
    # 响应式属性
    auto_scroll = reactive(True)
    max_display_count = reactive(500)
    
    class InfoAdded(Message):
        """信息添加消息"""
        def __init__(self, message: InfoMessage):
            super().__init__()
            self.message = message
    
    def __init__(self, title: str = "信息输出", **kwargs):
        """初始化信息面板"""
        super().__init__(**kwargs)
        self.border_title = title
        
        # 初始化组件
        self.buffer = InfoBuffer()
        self.logger = get_logger("info_panel")
        self.current_filters = {}
        self.display_widgets: List[InfoDisplay] = []
        
        # 新增AI建议管理器
        self.ai_display_widget = None
        self.ai_suggestions = []  # AI建议缓存
        self.thinking_animation = None  # 思考动画组件

        # 交易建议管理
        self.pending_trading_advice = {}  # 待确认的交易建议 {advice_id: TradingAdvice}
        self.trade_manager = None  # 交易管理器，将由应用程序设置
        self._pending_order_advice = None  # 临时保存待处理的订单建议（用于回调）

        # 与项目logger系统集成
        self._setup_logger_handler()
    
    @property
    def _app_instance(self):
        """获取app实例，兼容测试环境"""
        return getattr(self, '_app', None) or self.app
    
    def _setup_logger_handler(self) -> None:
        """设置logger处理器，自动捕获项目日志"""
        # 这里可以添加自定义的logging handler来捕获系统日志
        pass

    def set_trade_manager(self, trade_manager) -> None:
        """设置交易管理器"""
        self.trade_manager = trade_manager
        self.logger.debug("交易管理器已设置")
    
    async def on_mount(self) -> None:
        """组件挂载时初始化"""
        # 重构后的InfoPanel不再包含AI显示组件
        # AI功能已移至独立的AIDisplayWidget组件中
        self.ai_display_widget = None
        self.logger.debug("InfoPanel双面板组件初始化完成")
    
    def compose(self) -> ComposeResult:
        """组合信息面板 - 左右分栏设计"""
        # 左侧面板 - 信息选择区域 (50%)
        with Vertical(classes="left-panel", id="left_panel"):
            yield Static("📋 信息列表", classes="panel-title")
            yield InfoFilterBar(id="filter_bar")
            yield InfoMessageList(id="info_message_list", buffer=self.buffer)
            yield Static("就绪", classes="stats-bar", id="stats_bar")

        # 右侧面板 - 详细信息显示区域 (50%)
        with Vertical(classes="right-panel", id="right_panel"):
            yield Static("📄 详细信息", classes="panel-title")
            yield InfoDetailView(id="info_detail_view")
    
    async def on_info_filter_bar_filter_changed(self, event: InfoFilterBar.FilterChanged) -> None:
        """处理过滤条件改变"""
        self.current_filters = event.filters
        
        if "clear" in event.filters:
            await self.clear_all()
            return
        
        # 处理AI错误信息
        if "ai_error" in event.filters:
            await self.add_info(
                content=event.filters["ai_error"],
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )
            return
        
        # 处理显示AI对话框请求
        if "show_ai_dialog" in event.filters:
            # 使用 run_worker 在独立的 worker 中运行对话框，避免阻塞事件循环
            self.run_worker(self._show_ai_dialog(), exclusive=True, group="ai_dialog")
            return
        
        await self.refresh_display()
    
    async def add_info(self, 
                      content: str,
                      info_type: InfoType,
                      level: InfoLevel = InfoLevel.INFO,
                      source: str = "",
                      data: Optional[Dict[str, Any]] = None) -> None:
        """
        添加信息
        
        Args:
            content: 信息内容
            info_type: 信息类型
            level: 信息级别
            source: 信息源
            data: 附加数据
        """
        message = InfoMessage(
            content=content,
            info_type=info_type,
            level=level,
            timestamp=datetime.now(),
            source=source,
            data=data
        )
        
        self.buffer.add_message(message)
        await self.refresh_display()
        
        # 发送消息，处理测试环境
        try:
            self.post_message(self.InfoAdded(message))
        except (AttributeError, TypeError):
            # 在测试环境中可能没有post_message方法
            pass
    
    async def refresh_display(self) -> None:
        """刷新显示 - 适配双面板设计"""
        try:
            # 获取过滤后的消息
            filtered_messages = self._get_filtered_messages()

            # 刷新左侧消息列表
            message_list = self.query_one("#info_message_list", InfoMessageList)
            await message_list.refresh_messages(filtered_messages)

            # 更新统计信息
            await self._update_stats()

        except Exception as e:
            self.logger.error(f"刷新显示失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _get_filtered_messages(self) -> List[InfoMessage]:
        """获取过滤后的消息"""
        # 转换过滤条件
        info_types = None
        if self.current_filters.get("type"):
            try:
                info_types = [InfoType(self.current_filters["type"])]
            except ValueError:
                pass
        
        levels = None
        if self.current_filters.get("level"):
            try:
                levels = [InfoLevel(self.current_filters["level"])]
            except ValueError:
                pass
        
        search_text = self.current_filters.get("search")
        
        return self.buffer.get_filtered_messages(
            info_types=info_types,
            levels=levels,
            search_text=search_text
        )
    
    async def _update_stats(self) -> None:
        """更新统计信息"""
        stats = self.buffer.get_stats()
        filtered_count = len(self._get_filtered_messages())
        
        stats_text = f"总计: {stats['total']} | 显示: {filtered_count}"
        
        # 添加错误和警告计数
        if "error" in stats["by_level"]:
            stats_text += f" | 错误: {stats['by_level']['error']}"
        if "warning" in stats["by_level"]:
            stats_text += f" | 警告: {stats['by_level']['warning']}"
        
        stats_bar = self.query_one("#stats_bar")
        stats_bar.update(stats_text)
    
    async def remove_info_by_advice_id(self, advice_id: str) -> bool:
        """根据建议ID删除消息

        Args:
            advice_id: 交易建议ID

        Returns:
            bool: 是否成功删除
        """
        try:
            removed = self.buffer.remove_message_by_advice_id(advice_id)
            if removed:
                await self.refresh_display()
                self.logger.info(f"已删除建议消息: {advice_id[:8]}")
            return removed
        except Exception as e:
            self.logger.error(f"删除建议消息失败: {e}")
            return False

    async def clear_all(self) -> None:
        """清空所有信息"""
        try:
            self.buffer.clear()

            # 清空左侧消息列表
            message_list = self.query_one("#info_message_list", InfoMessageList)
            await message_list.refresh_messages([])

            # 重置右侧详情视图
            detail_view = self.query_one("#info_detail_view", InfoDetailView)
            await detail_view.query("*").remove()
            await detail_view.mount(Static("选择左侧消息查看详细信息", classes="detail-content", id="empty_detail"))

            await self._update_stats()
            self.logger.info("Info panel cleared")
        except Exception as e:
            self.logger.error(f"清空信息面板失败: {e}")

    async def on_info_message_list_message_selected(self, event: InfoMessageList.MessageSelected) -> None:
        """处理消息选择事件"""
        try:
            # 获取右侧详情视图组件
            detail_view = self.query_one("#info_detail_view", InfoDetailView)
            # 更新详情显示
            await detail_view.update_detail(event.message)
            self.logger.info(f"选择消息并更新详情: {event.message.content[:50]}...")
        except Exception as e:
            self.logger.error(f"处理消息选择事件失败: {e}")

    async def on_info_detail_view_trading_action_requested(self, event: InfoDetailView.TradingActionRequested) -> None:
        """处理详情视图的交易操作请求"""
        try:
            action = event.action
            advice_id = event.advice_id

            self.logger.info(f"收到交易操作请求: {action} for {advice_id[:8]}")

            # 直接构造命令字典并调用处理方法，避免通过文本解析
            command = {
                'action': action,
                'advice_id': advice_id
            }

            # 验证操作类型
            valid_actions = ['confirm', 'reject']
            if action in valid_actions:
                # 直接调用建议命令处理方法，传递完整的上下文
                await self._handle_advice_command(command)
            else:
                await self.add_info(
                    content=f"❌ 不支持的操作类型: {action}",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.ERROR,
                    source="操作处理"
                )

        except Exception as e:
            self.logger.error(f"处理交易操作请求失败: {e}")
            await self.add_info(
                content=f"❌ 处理操作请求时出现错误: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="操作处理"
            )
    
    # 便捷方法
    async def log_debug(self, content: str, source: str = "") -> None:
        """添加调试日志"""
        await self.add_info(content, InfoType.LOG, InfoLevel.DEBUG, source)
    
    async def log_info(self, content: str, source: str = "") -> None:
        """添加信息日志"""
        await self.add_info(content, InfoType.LOG, InfoLevel.INFO, source)
    
    async def log_warning(self, content: str, source: str = "") -> None:
        """添加警告日志"""
        await self.add_info(content, InfoType.LOG, InfoLevel.WARNING, source)
    
    async def log_error(self, content: str, source: str = "") -> None:
        """添加错误日志"""
        await self.add_info(content, InfoType.LOG, InfoLevel.ERROR, source)
    
    async def add_stock_data(self, content: str, data: Dict[str, Any], source: str = "") -> None:
        """添加股票数据"""
        await self.add_info(content, InfoType.STOCK_DATA, InfoLevel.INFO, source, data)
    
    async def add_trade_info(self, content: str, data: Dict[str, Any] = None, source: str = "") -> None:
        """添加交易信息"""
        await self.add_info(content, InfoType.TRADE_INFO, InfoLevel.INFO, source, data)
    
    async def add_performance_info(self, content: str, data: Dict[str, Any] = None, source: str = "") -> None:
        """添加性能信息"""
        await self.add_info(content, InfoType.PERFORMANCE, InfoLevel.INFO, source, data)

    async def select_last_message(self) -> bool:
        """选择最后一条消息并显示详情

        Returns:
            bool: 是否成功选择
        """
        try:
            message_list = self.query_one("#info_message_list", InfoMessageList)
            return await message_list.select_last_message()
        except Exception as e:
            self.logger.error(f"选择最后一条消息失败: {e}")
            return False

    async def _show_ai_dialog(self) -> None:
        """显示AI对话框并处理用户交互 - 优化版：快捷问题 + 自定义输入"""
        if not AI_MODULES_AVAILABLE:
            await self.add_info(
                content="AI功能不可用，请检查相关模块安装。",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )
            return

        try:
            # 导入快捷AI对话框组件
            from ..widgets.ai_quick_dialog import AIQuickDialog

            # 获取当前股票上下文
            context = self._get_current_trading_context()
            stock_code = context.get('current_stock', '')
            stock_name = context.get('stock_name', '')

            # 详细日志
            self.logger.info(f"[AI-DIALOG] 准备创建AI对话框")
            self.logger.info(f"[AI-DIALOG] 从context获取: stock_code={stock_code}, stock_name={stock_name}")

            # 验证app_core中的实际值
            if hasattr(self._app_instance, 'app_core'):
                app_core = self._app_instance.app_core
                actual_code = getattr(app_core, 'current_stock_code', None)
                self.logger.info(f"[AI-DIALOG] app_core.current_stock_code={actual_code}")

                if actual_code and hasattr(app_core, 'stock_basicinfo_cache'):
                    if actual_code in app_core.stock_basicinfo_cache:
                        actual_name = app_core.stock_basicinfo_cache[actual_code].get('name', '')
                        self.logger.info(f"[AI-DIALOG] 从basicinfo_cache获取名称: {actual_name}")

            # 创建快捷AI对话框
            ai_dialog = AIQuickDialog(
                stock_code=stock_code,
                stock_name=stock_name,
                dialog_id="ai_quick_dialog"
            )
            self.logger.info(f"[AI-DIALOG] AI对话框已创建: stock_code={stock_code}, stock_name={stock_name}")

            # 使用 await 直接等待对话框结果
            dialog_result = await self.app.push_screen_wait(ai_dialog)

            # 用户取消或未输入
            if dialog_result is None:
                self.logger.debug("用户取消AI对话")
                return

            # 解析对话框返回结果 (AIDialogResult: question, is_custom)
            if AIDialogResult and isinstance(dialog_result, AIDialogResult):
                user_input = dialog_result.question
                is_custom_input = dialog_result.is_custom
            else:
                # 兼容旧格式（纯字符串）
                user_input = str(dialog_result).strip() if dialog_result else ""
                is_custom_input = True  # 默认当作自定义输入处理

            if not user_input:
                self.logger.debug("用户未输入内容")
                return

            # 直接处理用户输入
            self.logger.info(f"收到用户AI请求: {user_input}, is_custom={is_custom_input}")
            await self._process_ai_request(user_input, use_tool_call=is_custom_input)

        except Exception as e:
            self.logger.error(f"AI对话框交互失败: {e}")
            await self.add_info(
                content=f"AI对话框交互失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )

    async def _process_ai_request(self, user_input: str, use_tool_call: bool = False) -> None:
        """处理AI请求并显示响应

        Args:
            user_input: 用户输入的问题
            use_tool_call: 是否使用tool use模式（自定义输入时为True，预设问题时为False）
        """
        self.logger.info(f"开始处理AI请求: {user_input}, use_tool_call={use_tool_call}")

        if not user_input.strip():
            self.logger.warning(f"用户输入为空，返回")
            return

        try:
            # 显示用户问题
            await self.add_info(
                content=f"用户提问: {user_input}",
                info_type=InfoType.USER_ACTION,
                level=InfoLevel.INFO,
                source="用户"
            )

            # 显示思考动画
            await self._start_thinking_animation()

            # 创建AI客户端并获取响应
            ai_client = await create_claude_client()
            if not ai_client.is_available():
                await self.add_info(
                    content="AI服务暂不可用，请稍后重试。",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.ERROR,
                    source="AI助手"
                )
                return

            # 统一准备上下文数据 - 一次性构建完整context
            context = self._prepare_unified_context()
            stock_code = context.get('current_stock', 'HK.00700')

            # 自定义输入：使用 chat_with_ai 方法走 tool use 流程
            if use_tool_call:
                self.logger.info(f"自定义输入，使用 chat_with_ai (tool use 模式)")

                # 创建进度消息ID，用于更新同一条消息
                self._tool_use_progress_parts = ["🔄 AI正在分析..."]

                # 创建进度回调函数
                def tool_use_progress_callback(event_type: str, data: dict):
                    """Tool use 进度回调"""
                    tool_name_map = {
                        'get_realtime_quote': '实时行情',
                        'get_stock_kline': 'K线数据',
                        'get_capital_flow': '资金流向',
                        'get_orderbook': '五档买卖盘',
                        'get_stock_basicinfo': '基本信息'
                    }

                    if event_type == 'tool_start':
                        tool_name = data.get('tool_name', '')
                        display_name = tool_name_map.get(tool_name, tool_name)
                        self._tool_use_progress_parts.append(f"📡 正在获取{display_name}...")
                        self.logger.info(f"[PROGRESS] 工具调用开始: {display_name}")

                    elif event_type == 'tool_end':
                        tool_name = data.get('tool_name', '')
                        display_name = tool_name_map.get(tool_name, tool_name)
                        # 更新最后一条为完成状态
                        if self._tool_use_progress_parts:
                            self._tool_use_progress_parts[-1] = f"✅ 已获取{display_name}"
                        self.logger.info(f"[PROGRESS] 工具调用完成: {display_name}")

                    elif event_type == 'thinking':
                        self._tool_use_progress_parts.append("🤔 AI正在分析数据...")
                        self.logger.info(f"[PROGRESS] AI继续思考...")

                # 调用支持 tool use 的对话方法
                response_text = await ai_client.chat_with_ai(
                    user_message=user_input,
                    stock_context=context,
                    use_tools=True,
                    progress_callback=tool_use_progress_callback
                )

                # 停止思考动画
                await self._stop_thinking_animation()

                # 显示AI回复（包含工具调用过程）
                await self._display_chat_response_with_progress(response_text, self._tool_use_progress_parts)
                return

            # 预设问题：走原有的结构化分析流程
            # 如果技术指标为空，主动加载分析数据
            if not context.get('technical_indicators'):
                self.logger.info(f"技术指标为空，主动加载股票 {stock_code} 的分析数据...")
                await self._ensure_analysis_data_loaded(stock_code)
                # 重新准备上下文以获取最新的技术指标
                context = self._prepare_unified_context()

            # 检测是否为明确的交易操作请求
            if self._is_explicit_trading_request(user_input):
                # 生成交易建议 - 使用统一的请求对象
                self.logger.info(f"Process_ai_request 检测到交易操作请求，生成交易建议")

                # 创建交易建议请求对象
                advice_request = AITradingAdviceRequest(
                    stock_code=stock_code,
                    user_input=user_input,
                    context=context,  # 使用统一的完整context
                    available_funds=context.get('available_funds', 50000.0),
                    current_position=context.get('current_position', '无持仓')
                )

                advice = await ai_client.generate_trading_advice(advice_request)

                # 停止思考动画
                await self._stop_thinking_animation()

                # 显示交易建议（会触发按钮显示）
                await self._display_trading_advice(advice)
            else:
                # 使用股票分析方法处理普通分析请求 - 使用统一的请求对象
                self.logger.info(f"Process_ai_request 检测到分析请求，生成股票分析")

                # 创建分析请求对象 - 使用相同的统一context
                analysis_request = AIAnalysisRequest(
                    stock_code=stock_code,
                    user_input=user_input,
                    context=context,  # 使用统一的完整context
                    analysis_type='comprehensive'
                )

                # 调试日志：检查技术指标是否传递
                tech_indicators = analysis_request.get_technical_indicators()
                if tech_indicators:
                    self.logger.info(f"✓ 技术指标已传递到分析请求: MA5={tech_indicators.get('ma5')}, RSI={tech_indicators.get('rsi')}")
                else:
                    self.logger.warning(f"✗ 技术指标为空! context keys: {context.keys()}")

                # 调用股票分析方法
                analysis_response = await ai_client.generate_stock_analysis(analysis_request)

                # 停止思考动画
                await self._stop_thinking_animation()

                # 显示AI分析回复（使用结构化响应）
                await self._display_analysis_response(analysis_response)

        except Exception as e:
            # 确保停止动画
            await self._stop_thinking_animation()

            self.logger.error(f"处理AI请求失败: {e}")
            await self.add_info(
                content=f"AI处理失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )
    
    def _is_explicit_trading_request(self, user_input: str) -> bool:
        """检测是否为明确的交易操作请求

        只有包含明确交易操作词汇的请求才会触发交易建议生成
        避免将普通分析问题误判为交易请求
        """
        explicit_trading_keywords = [
            '买卖', '买入', '卖出', '下单', '建仓', '平仓', '加仓', '减仓',
            '市价单', '限价单', '止损单', '止盈单',
            '帮我买', '帮我卖', '我要买', '我要卖',
            '建议买', '建议卖', '应该买', '应该卖',
            '给个交易建议', '交易策略', '操作建议'
        ]

        user_lower = user_input.lower()
        return any(keyword in user_lower for keyword in explicit_trading_keywords)

    def _extract_stock_code(self, user_input: str) -> str:
        """从用户输入中提取股票代码"""
        import re

        # 匹配常见的股票代码格式
        patterns = [
            r'([A-Z]{2}\.[0-9]{5})',  # HK.00700
            r'([A-Z]{2}\.[A-Z]{3,4})',  # US.AAPL
            r'([SH|SZ]\.[0-9]{6})',  # SH.600000, SZ.000001
            r'([0-9]{6})',  # 000001, 600000
            r'([A-Z]{3,4})'  # AAPL
        ]

        for pattern in patterns:
            match = re.search(pattern, user_input.upper())
            if match:
                return match.group(1)

        return ""

    def _prepare_unified_context(self) -> dict:
        """统一准备AI请求的完整上下文数据

        返回包含所有必要信息的结构化context，供两种AI请求共享使用

        Returns:
            dict: 包含以下结构的完整上下文：
                - current_stock: 当前股票代码
                - stock_name: 股票名称
                - available_funds: 可用资金
                - current_position: 当前持仓
                - basic_info: 基本信息字典
                - realtime_quote: 实时报价字典
                - technical_indicators: 技术指标字典
        """
        try:
            # 尝试从app_core中获取当前股票信息
            app = self._app_instance
            context = {}

            # 从app_core获取股票代码
            if hasattr(app, 'app_core'):
                app_core = app.app_core

                # 获取当前股票代码
                if hasattr(app_core, 'current_stock_code') and app_core.current_stock_code:
                    stock_code = app_core.current_stock_code
                    context['current_stock'] = stock_code

                    # 从缓存获取股票基本信息
                    if hasattr(app_core, 'stock_basicinfo_cache') and stock_code in app_core.stock_basicinfo_cache:
                        stock_info = app_core.stock_basicinfo_cache[stock_code]
                        context['stock_name'] = stock_info.get('name', '')

                        # 构建结构化的基本信息
                        context['basic_info'] = {
                            'code': stock_code,
                            'name': stock_info.get('name', ''),
                            'stock_type': stock_info.get('stock_type', '未知')
                        }

                    # 从stock_data获取实时价格信息
                    if hasattr(app_core, 'stock_data') and stock_code in app_core.stock_data:
                        stock_data = app_core.stock_data[stock_code]

                        # 构建结构化的实时报价
                        context['realtime_quote'] = {
                            'cur_price': getattr(stock_data, 'current_price', 0),
                            'change_rate': getattr(stock_data, 'change_rate', 0),
                            'volume': getattr(stock_data, 'volume', 0),
                            'turnover_rate': getattr(stock_data, 'turnover_rate', 0)
                        }

                        # 同时保留顶层字段以兼容旧代码
                        context['current_price'] = getattr(stock_data, 'current_price', None)
                        context['change_rate'] = getattr(stock_data, 'change_rate', None)
                        context['volume'] = getattr(stock_data, 'volume', None)

                    # 从分析数据管理器获取技术指标和资金流向
                    if hasattr(app_core, 'analysis_data_manager'):
                        analysis_data_manager = app_core.analysis_data_manager
                        self.logger.debug(f"检查股票 {stock_code} 的分析数据缓存...")
                        # 检查是否有该股票的分析数据缓存
                        if stock_code in analysis_data_manager.analysis_data_cache:
                            analysis_data = analysis_data_manager.analysis_data_cache[stock_code]

                            # 获取技术指标数据
                            if hasattr(analysis_data, 'technical_indicators') and analysis_data.technical_indicators:
                                context['technical_indicators'] = analysis_data.technical_indicators
                                self.logger.info(f"✓ 成功获取股票 {stock_code} 技术指标: MA5={analysis_data.technical_indicators.get('ma5')}, RSI={analysis_data.technical_indicators.get('rsi')}")
                            else:
                                self.logger.warning(f"✗ 股票 {stock_code} 分析数据中无技术指标")

                            # 获取资金流向数据
                            if hasattr(analysis_data, 'capital_flow') and analysis_data.capital_flow:
                                context['capital_flow'] = analysis_data.capital_flow
                                self.logger.info(f"✓ 成功获取股票 {stock_code} 资金流向数据")
                            else:
                                self.logger.debug(f"股票 {stock_code} 分析数据中无资金流向（将在需要时动态获取）")

                            # 获取五档买卖盘数据
                            if hasattr(analysis_data, 'orderbook_data') and analysis_data.orderbook_data:
                                orderbook = analysis_data.orderbook_data
                                context['orderbook'] = {
                                    'ask': [
                                        {'price': getattr(orderbook, 'ask_price_1', 0), 'volume': getattr(orderbook, 'ask_volume_1', 0)},
                                        {'price': getattr(orderbook, 'ask_price_2', 0), 'volume': getattr(orderbook, 'ask_volume_2', 0)},
                                        {'price': getattr(orderbook, 'ask_price_3', 0), 'volume': getattr(orderbook, 'ask_volume_3', 0)},
                                        {'price': getattr(orderbook, 'ask_price_4', 0), 'volume': getattr(orderbook, 'ask_volume_4', 0)},
                                        {'price': getattr(orderbook, 'ask_price_5', 0), 'volume': getattr(orderbook, 'ask_volume_5', 0)},
                                    ],
                                    'bid': [
                                        {'price': getattr(orderbook, 'bid_price_1', 0), 'volume': getattr(orderbook, 'bid_volume_1', 0)},
                                        {'price': getattr(orderbook, 'bid_price_2', 0), 'volume': getattr(orderbook, 'bid_volume_2', 0)},
                                        {'price': getattr(orderbook, 'bid_price_3', 0), 'volume': getattr(orderbook, 'bid_volume_3', 0)},
                                        {'price': getattr(orderbook, 'bid_price_4', 0), 'volume': getattr(orderbook, 'bid_volume_4', 0)},
                                        {'price': getattr(orderbook, 'bid_price_5', 0), 'volume': getattr(orderbook, 'bid_volume_5', 0)},
                                    ]
                                }
                                self.logger.info(f"✓ 成功获取股票 {stock_code} 五档买卖盘数据")
                            else:
                                self.logger.debug(f"股票 {stock_code} 分析数据中无五档买卖盘")

                            # 获取K线数据
                            if hasattr(analysis_data, 'kline_data') and analysis_data.kline_data:
                                kline_list = []
                                for kline in analysis_data.kline_data:
                                    kline_list.append({
                                        'time_key': getattr(kline, 'time_key', ''),
                                        'open': getattr(kline, 'open', 0),
                                        'high': getattr(kline, 'high', 0),
                                        'low': getattr(kline, 'low', 0),
                                        'close': getattr(kline, 'close', 0),
                                        'volume': getattr(kline, 'volume', 0),
                                        'change_rate': getattr(kline, 'change_rate', 0)
                                    })
                                context['kline_data'] = kline_list
                                self.logger.info(f"✓ 成功获取股票 {stock_code} K线数据: {len(kline_list)}根")
                            else:
                                self.logger.debug(f"股票 {stock_code} 分析数据中无K线数据")
                        else:
                            self.logger.warning(f"✗ 股票 {stock_code} 不在分析数据缓存中，可用股票: {list(analysis_data_manager.analysis_data_cache.keys())}")
                    else:
                        self.logger.warning(f"✗ app_core 没有 analysis_data_manager 属性")

                # 获取交易模式和持仓/资金信息
                self._add_trading_context(app, app_core, context)

            # 设置默认值
            context.setdefault('current_stock', 'HK.00700')
            context.setdefault('stock_name', '腾讯控股')
            context.setdefault('available_funds', 0.0)
            context.setdefault('current_position', '无持仓')
            context.setdefault('trading_mode', '模拟交易')
            context.setdefault('position_list', [])
            context.setdefault('account_info', {})

            # 确保结构化字段存在
            context.setdefault('basic_info', {
                'code': context['current_stock'],
                'name': context['stock_name']
            })
            context.setdefault('realtime_quote', {})
            context.setdefault('technical_indicators', {})
            context.setdefault('capital_flow', {})
            context.setdefault('orderbook', {})
            context.setdefault('kline_data', [])

            return context

        except Exception as e:
            self.logger.warning(f"准备统一上下文失败: {e}，使用默认值")
            return {
                'current_stock': 'HK.00700',
                'stock_name': '腾讯控股',
                'current_price': 425.0,
                'change_rate': '+2.35%',
                'available_funds': 50000.0,
                'current_position': '无持仓',
                'basic_info': {
                    'code': 'HK.00700',
                    'name': '腾讯控股'
                },
                'realtime_quote': {
                    'cur_price': 425.0,
                    'change_rate': 2.35,
                    'volume': 0
                },
                'technical_indicators': {},
                'capital_flow': {},
                'orderbook': {},
                'kline_data': [],
                'trading_mode': '模拟交易',
                'position_list': [],
                'account_info': {}
            }

    def _add_trading_context(self, app, app_core, context: dict) -> None:
        """添加交易模式、持仓和资金信息到上下文

        Args:
            app: 应用实例
            app_core: 应用核心实例
            context: 上下文字典（会被修改）
        """
        try:
            # 获取当前交易模式
            from ..main.data import CURRENT_TRADING_MODE, TRADING_MODE_SIMULATION, TRADING_MODE_REAL

            trading_mode = CURRENT_TRADING_MODE
            context['trading_mode'] = trading_mode

            # 根据交易模式确定富途API的trd_env参数
            trd_env = "SIMULATE" if trading_mode == TRADING_MODE_SIMULATION else "REAL"
            context['trd_env'] = trd_env

            self.logger.debug(f"当前交易模式: {trading_mode}, trd_env: {trd_env}")

            # 获取当前股票代码用于筛选持仓
            current_stock = context.get('current_stock', '')

            # 获取持仓数据
            if hasattr(app_core, 'position_data') and app_core.position_data:
                position_list = []
                current_stock_position = None

                for pos in app_core.position_data:
                    position_info = {
                        'stock_code': pos.get('stock_code', ''),
                        'stock_name': pos.get('stock_name', ''),
                        'qty': pos.get('qty', 0),
                        'can_sell_qty': pos.get('can_sell_qty', 0),
                        'cost_price': pos.get('cost_price', 0),
                        'market_val': pos.get('market_val', 0),
                        'pl_val': pos.get('pl_val', 0),
                        'pl_ratio': pos.get('pl_ratio', 0)
                    }
                    position_list.append(position_info)

                    # 检查是否为当前股票的持仓
                    if pos.get('stock_code', '') == current_stock:
                        current_stock_position = position_info

                context['position_list'] = position_list

                # 构建当前持仓描述
                if current_stock_position:
                    qty = current_stock_position.get('qty', 0)
                    cost_price = current_stock_position.get('cost_price', 0)
                    pl_ratio = current_stock_position.get('pl_ratio', 0)
                    context['current_position'] = f"持有{qty}股，成本价{cost_price:.2f}，盈亏{pl_ratio:.2f}%"
                elif position_list:
                    context['current_position'] = f"持有{len(position_list)}只股票，但不包含当前股票"
                else:
                    context['current_position'] = "无持仓"

                self.logger.info(f"✓ 成功获取持仓数据: {len(position_list)}只股票")
            else:
                context['position_list'] = []
                context['current_position'] = "无持仓"

            # 获取账户资金信息
            futu_trade = getattr(app, 'futu_trade', None)
            if futu_trade:
                try:
                    # 根据当前股票确定市场
                    market = "HK"
                    if current_stock.startswith("US."):
                        market = "US"
                    elif current_stock.startswith(("SH.", "SZ.")):
                        market = "CN"

                    # 获取账户信息
                    account_info = futu_trade.get_account_info(trd_env=trd_env, market=market)

                    if account_info:
                        context['account_info'] = {
                            'total_assets': account_info.get('total_assets', 0),
                            'cash': account_info.get('cash', 0),
                            'market_val': account_info.get('market_val', 0),
                            'frozen_cash': account_info.get('frozen_cash', 0),
                            'avl_withdrawal_cash': account_info.get('avl_withdrawal_cash', 0),
                            'currency': account_info.get('currency', 'HKD')
                        }
                        # 可用资金 = 现金 - 冻结资金
                        available_funds = account_info.get('cash', 0) - account_info.get('frozen_cash', 0)
                        context['available_funds'] = available_funds

                        self.logger.info(f"✓ 成功获取{trading_mode}账户资金: 可用{available_funds:.2f}, 总资产{account_info.get('total_assets', 0):.2f}")
                    else:
                        self.logger.warning(f"获取{trading_mode}账户信息返回空")
                except Exception as e:
                    self.logger.error(f"获取账户资金信息失败: {e}")
            else:
                self.logger.debug("futu_trade 未初始化，跳过账户资金获取")

            # 获取当日待成交订单和成交记录
            if futu_trade:
                self._add_orders_and_deals_context(futu_trade, trd_env, market, current_stock, context)

        except Exception as e:
            self.logger.error(f"添加交易上下文失败: {e}")
            context['trading_mode'] = '模拟交易'
            context['trd_env'] = 'SIMULATE'

    def _add_orders_and_deals_context(self, futu_trade, trd_env: str, market: str, current_stock: str, context: dict) -> None:
        """添加订单和成交记录到上下文

        Args:
            futu_trade: 富途交易实例
            trd_env: 交易环境（SIMULATE/REAL）
            market: 市场（HK/US/CN）
            current_stock: 当前股票代码
            context: 上下文字典（会被修改）
        """
        try:
            # 获取当日待成交订单（状态为SUBMITTED的订单）
            pending_orders = futu_trade.get_order_list(
                order_status='SUBMITTED',
                trd_env=trd_env,
                market=market
            )

            if pending_orders:
                orders_list = []
                current_stock_orders = []

                for order in pending_orders:
                    order_info = {
                        'order_id': order.get('order_id', ''),
                        'stock_code': order.get('code', ''),
                        'stock_name': order.get('stock_name', ''),
                        'trd_side': order.get('trd_side', ''),  # BUY/SELL
                        'order_type': order.get('order_type', ''),
                        'qty': order.get('qty', 0),
                        'price': order.get('price', 0),
                        'dealt_qty': order.get('dealt_qty', 0),
                        'dealt_avg_price': order.get('dealt_avg_price', 0),
                        'create_time': order.get('create_time', ''),
                        'order_status': order.get('order_status', '')
                    }
                    orders_list.append(order_info)

                    # 筛选当前股票的订单
                    if order.get('code', '') == current_stock:
                        current_stock_orders.append(order_info)

                context['pending_orders'] = orders_list
                context['current_stock_pending_orders'] = current_stock_orders

                self.logger.info(f"✓ 成功获取待成交订单: {len(orders_list)}笔, 当前股票{len(current_stock_orders)}笔")
            else:
                context['pending_orders'] = []
                context['current_stock_pending_orders'] = []

            # 获取当日成交记录
            today_deals = futu_trade.get_deal_list(
                trd_env=trd_env,
                market=market
            )

            if today_deals:
                deals_list = []
                current_stock_deals = []

                for deal in today_deals:
                    deal_info = {
                        'deal_id': deal.get('deal_id', ''),
                        'order_id': deal.get('order_id', ''),
                        'stock_code': deal.get('code', ''),
                        'stock_name': deal.get('stock_name', ''),
                        'trd_side': deal.get('trd_side', ''),  # BUY/SELL
                        'qty': deal.get('qty', 0),
                        'price': deal.get('price', 0),
                        'create_time': deal.get('create_time', ''),
                        'counter_broker_id': deal.get('counter_broker_id', ''),
                        'counter_broker_name': deal.get('counter_broker_name', '')
                    }
                    deals_list.append(deal_info)

                    # 筛选当前股票的成交
                    if deal.get('code', '') == current_stock:
                        current_stock_deals.append(deal_info)

                context['today_deals'] = deals_list
                context['current_stock_deals'] = current_stock_deals

                self.logger.info(f"✓ 成功获取当日成交: {len(deals_list)}笔, 当前股票{len(current_stock_deals)}笔")
            else:
                context['today_deals'] = []
                context['current_stock_deals'] = []

        except Exception as e:
            self.logger.error(f"获取订单和成交记录失败: {e}")
            context['pending_orders'] = []
            context['today_deals'] = []
            context['current_stock_pending_orders'] = []
            context['current_stock_deals'] = []

    def _get_current_trading_context(self) -> dict:
        """获取当前交易上下文（向后兼容方法）

        注意：此方法已被 _prepare_unified_context 替代
        保留此方法仅为向后兼容
        """
        return self._prepare_unified_context()

    async def _ensure_analysis_data_loaded(self, stock_code: str) -> bool:
        """确保股票的分析数据已加载（包括技术指标）

        Args:
            stock_code: 股票代码

        Returns:
            bool: 是否成功加载分析数据
        """
        try:
            app = self._app_instance
            if not hasattr(app, 'app_core'):
                self.logger.warning("app_core 不存在，无法加载分析数据")
                return False

            app_core = app.app_core

            # 检查是否有分析数据管理器
            if not hasattr(app_core, 'analysis_data_manager'):
                self.logger.warning("analysis_data_manager 不存在，无法加载分析数据")
                return False

            analysis_data_manager = app_core.analysis_data_manager

            # 如果缓存中已有数据，检查是否包含技术指标
            if stock_code in analysis_data_manager.analysis_data_cache:
                analysis_data = analysis_data_manager.analysis_data_cache[stock_code]
                if hasattr(analysis_data, 'technical_indicators') and analysis_data.technical_indicators:
                    self.logger.debug(f"股票 {stock_code} 分析数据已存在且包含技术指标")
                    return True

            # 主动加载分析数据
            self.logger.info(f"主动加载股票 {stock_code} 的分析数据和技术指标...")
            analysis_data = await analysis_data_manager.load_analysis_data(stock_code)

            if analysis_data and analysis_data.technical_indicators:
                self.logger.info(f"✓ 成功加载股票 {stock_code} 的技术指标: MA5={analysis_data.technical_indicators.get('ma5')}, RSI={analysis_data.technical_indicators.get('rsi')}")
                return True
            else:
                self.logger.warning(f"✗ 加载股票 {stock_code} 的分析数据失败或无技术指标")
                return False

        except Exception as e:
            self.logger.error(f"确保分析数据加载失败: {e}")
            return False

    async def _display_chat_response(self, response_text: str) -> None:
        """显示AI对话响应（tool use模式的返回结果）

        Args:
            response_text: AI响应的文本内容
        """
        try:
            if not response_text:
                await self.add_info(
                    content="AI未返回有效响应",
                    info_type=InfoType.WARNING,
                    level=InfoLevel.WARNING,
                    source="AI助手"
                )
                return

            # 构建格式化的对话响应
            content_parts = [
                "💬 AI智能回复",
                "=" * 50,
                "",
                response_text
            ]

            formatted_content = "\n".join(content_parts)

            # 显示AI回复
            await self.add_info(
                content=formatted_content,
                info_type=InfoType.LOG,
                level=InfoLevel.INFO,
                source="AI助手"
            )

            # 自动选中AI回复的消息，方便用户查看详情
            await self.select_last_message()

        except Exception as e:
            self.logger.error(f"显示对话响应失败: {e}")
            await self.add_info(
                content=f"显示AI回复失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )

    async def _display_chat_response_with_progress(self, response_text: str, progress_parts: list) -> None:
        """显示AI对话响应（包含tool use进度信息）

        Args:
            response_text: AI响应的文本内容
            progress_parts: 工具调用进度信息列表
        """
        try:
            if not response_text:
                await self.add_info(
                    content="AI未返回有效响应",
                    info_type=InfoType.WARNING,
                    level=InfoLevel.WARNING,
                    source="AI助手"
                )
                return

            # 构建包含进度信息的格式化响应
            content_parts = [
                "💬 AI智能回复 (Tool Use)",
                "=" * 50,
                "",
                "📋 数据获取过程:",
            ]

            # 添加进度信息
            for progress in progress_parts:
                content_parts.append(f"  {progress}")

            content_parts.extend([
                "",
                "-" * 50,
                "",
                "📝 分析结果:",
                response_text
            ])

            formatted_content = "\n".join(content_parts)

            # 显示AI回复
            await self.add_info(
                content=formatted_content,
                info_type=InfoType.LOG,
                level=InfoLevel.INFO,
                source="AI助手"
            )

            # 自动选中AI回复的消息，方便用户查看详情
            await self.select_last_message()

        except Exception as e:
            self.logger.error(f"显示对话响应失败: {e}")
            await self.add_info(
                content=f"显示AI回复失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )

    async def _display_analysis_response(self, response) -> None:
        """显示AI股票分析响应

        Args:
            response: AIAnalysisResponse 对象
        """
        try:
            from ...base.ai import AIAnalysisResponse

            if not isinstance(response, AIAnalysisResponse):
                self.logger.error(f"无效的分析响应类型: {type(response)}")
                await self.add_info(
                    content="AI分析响应格式错误",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.ERROR,
                    source="AI助手"
                )
                return

            # 构建格式化的分析内容
            content_parts = [
                f"📊 AI股票分析 - {response.stock_code}",
                f"分析类型: {self._get_analysis_type_display(response.analysis_type)}",
                f"置信度: {response.confidence_score:.2%}",
                f"风险等级: {response.risk_level}",
                "",
                "=" * 50,
                ""
            ]

            # 添加关键点
            if response.key_points:
                content_parts.append("🔑 关键要点:")
                for idx, point in enumerate(response.key_points, 1):
                    content_parts.append(f"  {idx}. {point}")
                content_parts.append("")

            # 添加主要分析内容
            content_parts.append("📝 详细分析:")
            content_parts.append(response.content)
            content_parts.append("")

            # 添加投资建议
            if response.recommendation:
                content_parts.append("💡 投资建议:")
                content_parts.append(response.recommendation)

            # 组合所有内容
            formatted_content = "\n".join(content_parts)

            # 显示分析结果
            await self.add_info(
                content=formatted_content,
                info_type=InfoType.LOG,
                level=InfoLevel.INFO,
                source="AI分析助手"
            )

            # 自动选中AI回复的消息，方便用户查看详情
            await self.select_last_message()

        except Exception as e:
            self.logger.error(f"显示分析响应失败: {e}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            await self.add_info(
                content=f"显示分析结果失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI助手"
            )

    def _get_analysis_type_display(self, analysis_type: str) -> str:
        """获取分析类型的显示名称"""
        type_names = {
            'technical': '技术分析',
            'fundamental': '基本面分析',
            'comprehensive': '综合分析',
            'risk_assessment': '风险评估',
            'capital_flow': '资金流向分析'
        }
        return type_names.get(analysis_type, '未知分析')

    async def _display_trading_advice(self, advice: TradingAdvice) -> None:
        """显示交易建议"""
        try:
            # 缓存建议以供用户确认
            self.pending_trading_advice[advice.advice_id] = advice

            # 构建建议显示内容
            advice_content = self._format_trading_advice(advice)

            # 显示建议
            await self.add_info(
                content=advice_content,
                info_type=InfoType.TRADE_ADVICE,
                level=InfoLevel.INFO,
                source="AI交易助手",
                data={
                    'advice_id': advice.advice_id,
                    'recommended_action': advice.recommended_action,
                    'confidence_score': advice.confidence_score,
                    'risk_assessment': advice.risk_assessment,
                    'suggested_orders': len(advice.suggested_orders)
                }
            )

            # 自动选中AI回复的消息，方便用户查看详情
            await self.select_last_message()

        except Exception as e:
            self.logger.error(f"显示交易建议失败: {e}")
            await self.add_info(
                content=f"建议显示失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="AI交易助手"
            )

    def _format_trading_advice(self, advice: TradingAdvice) -> str:
        """格式化交易建议显示"""
        content = [
            f"📊 AI交易建议 (ID: {advice.advice_id[:8]})",
            f"🎯 建议摘要: {advice.advice_summary}",
            f"📈 推荐操作: {advice.recommended_action}",
            f"⚖️ 风险评估: {advice.risk_assessment}",
            f"🎯 置信度: {advice.confidence_score:.2f}",
            ""
        ]

        if advice.key_points:
            content.append("🔑 关键要点:")
            for point in advice.key_points:
                content.append(f"  • {point}")
            content.append("")

        if advice.suggested_orders:
            content.append("📋 建议订单:")
            for i, order in enumerate(advice.suggested_orders, 1):
                price_text = f"{order.price}元" if order.price else "市价"
                content.append(f"  {i}. {order.stock_code} {order.action} {order.quantity}股 @ {price_text}")
                if order.trigger_price:
                    content.append(f"     触发价: {order.trigger_price}元")
            content.append("")

        if advice.risk_factors:
            content.append("⚠️ 风险因素:")
            for risk in advice.risk_factors:
                content.append(f"  • {risk}")

        return "\n".join(content)

    async def _handle_advice_command(self, command: dict) -> None:
        """处理建议确认命令"""
        try:
            # 停止思考动画
            await self._stop_thinking_animation()

            action = command['action']
            advice_id = command['advice_id']

            if advice_id not in self.pending_trading_advice:
                await self.add_info(
                    content=f"❌ 未找到建议 {advice_id[:8]}，可能已过期或不存在",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.WARNING,
                    source="交易确认系统"
                )
                return

            advice = self.pending_trading_advice[advice_id]

            if action == 'confirm':
                await self._execute_trading_advice(advice)
            elif action == 'reject':
                await self._reject_trading_advice(advice)

        except Exception as e:
            await self._stop_thinking_animation()
            self.logger.error(f"处理建议命令失败: {e}")
            await self.add_info(
                content=f"命令处理失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="交易确认系统"
            )

    def _convert_trading_order_to_order_data(self, trading_order, stock_name: str = ""):
        """将AI建议的TradingOrder转换为订单对话框的OrderData"""
        from ...base.order import OrderData

        # 转换买卖方向
        trd_side = "BUY" if trading_order.action.lower() == 'buy' else "SELL"

        # 转换订单类型
        order_type_map = {
            'MARKET': 'MARKET',
            'NORMAL': 'NORMAL',
            'STOP': 'STOP',
            'STOP_LIMIT': 'STOP_LIMIT'
        }
        order_type = order_type_map.get(trading_order.order_type, 'MARKET')

        # 从股票代码推断市场
        market = "HK"
        if trading_order.stock_code.startswith("US."):
            market = "US"
        elif trading_order.stock_code.startswith("SH.") or trading_order.stock_code.startswith("SZ."):
            market = "CN"

        # 创建OrderData对象
        order_data = OrderData(
            code=trading_order.stock_code,
            price=trading_order.price if trading_order.price else 0.0,
            qty=trading_order.quantity,
            order_type=order_type,
            trd_side=trd_side,
            trd_env="SIMULATE",
            market=market,
            aux_price=trading_order.trigger_price,
            time_in_force="DAY",
            remark=f"AI建议: {stock_name}"
        )

        return order_data

    async def _execute_trading_advice(self, advice: TradingAdvice) -> None:
        """执行交易建议 - 弹出订单对话框让用户确认"""
        try:
            await self.add_info(
                content=f"🔄 准备执行建议 {advice.advice_id[:8]}...",
                info_type=InfoType.TRADE_INFO,
                level=InfoLevel.INFO,
                source="交易执行系统"
            )

            if not self.trade_manager:
                await self.add_info(
                    content="❌ 交易管理器未初始化，无法执行交易",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.ERROR,
                    source="交易执行系统"
                )
                return

            # 检查是否有建议的订单
            if not advice.suggested_orders:
                await self.add_info(
                    content="❌ 建议中没有具体订单信息",
                    info_type=InfoType.ERROR,
                    level=InfoLevel.ERROR,
                    source="交易执行系统"
                )
                return

            # 取第一个建议订单作为默认值
            suggested_order = advice.suggested_orders[0]

            # 转换为OrderData格式
            default_order_data = self._convert_trading_order_to_order_data(
                suggested_order,
                advice.stock_name
            )

            # 准备默认值字典
            default_values = {
                "code": default_order_data.code,
                "trd_side": default_order_data.trd_side,
                "order_type": default_order_data.order_type,
                "qty": str(default_order_data.qty),
                "price": str(default_order_data.price) if default_order_data.price else "",
                "aux_price": str(default_order_data.aux_price) if default_order_data.aux_price else "",
                "trd_env": default_order_data.trd_env,
                "market": default_order_data.market,
                "time_in_force": default_order_data.time_in_force,
                "remark": default_order_data.remark
            }

            # 弹出订单对话框
            dialog = PlaceOrderDialog(
                title=f"确认AI交易建议 - {advice.stock_name}",
                default_values=default_values,
                dialog_id=f"ai_advice_{advice.advice_id}"
            )

            # 保存advice引用，供回调使用
            self._pending_order_advice = advice

            # 使用 push_screen 并提供回调函数
            self.app.push_screen(dialog, self._on_order_dialog_result)

        except Exception as e:
            self.logger.error(f"执行交易建议失败: {e}")
            await self.add_info(
                content=f"❌ 执行过程异常: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="交易执行系统"
            )

    async def _on_order_dialog_result(self, order_data) -> None:
        """处理订单对话框的结果回调

        Args:
            order_data: OrderData对象（用户确认）或 None（用户取消）
        """
        try:
            # 获取之前保存的advice
            advice = getattr(self, '_pending_order_advice', None)
            if not advice:
                self.logger.error("未找到待处理的建议")
                return

            if order_data:
                # 用户确认了订单（dismiss返回OrderData对象）
                await self.add_info(
                    content=f"✅ 用户确认订单: {order_data.code} {order_data.trd_side} {order_data.qty}股 @ {order_data.price}",
                    info_type=InfoType.USER_ACTION,
                    level=InfoLevel.INFO,
                    source="用户操作"
                )

                # 执行订单 - FutuTrade.place_order是同步方法，需要在executor中运行
                import asyncio
                loop = asyncio.get_event_loop()
                exec_result = await loop.run_in_executor(
                    None,
                    lambda: self.trade_manager.place_order(
                        code=order_data.code,
                        price=order_data.price,
                        qty=order_data.qty,
                        order_type=order_data.order_type,
                        trd_side=order_data.trd_side,
                        aux_price=order_data.aux_price,
                        trd_env=order_data.trd_env,
                        market=order_data.market
                    )
                )

                if exec_result.get("success"):
                    # 删除原始AI建议消息
                    await self.remove_info_by_advice_id(advice.advice_id)

                    await self.add_info(
                        content=f"✅ 订单执行成功: {order_data.code} {order_data.trd_side} {order_data.qty}股",
                        info_type=InfoType.TRADE_INFO,
                        level=InfoLevel.INFO,
                        source="订单执行",
                        data=exec_result
                    )

                    # 更新建议状态
                    advice.status = "executed"
                else:
                    # 获取详细错误信息
                    error_msg = exec_result.get('error') or exec_result.get('message') or exec_result.get('msg') or '未知错误'
                    await self.add_info(
                        content=f"❌ 订单执行失败: {error_msg}",
                        info_type=InfoType.ERROR,
                        level=InfoLevel.ERROR,
                        source="订单执行",
                        data=exec_result
                    )
            else:
                # 用户取消了订单（dismiss返回None）
                await self.add_info(
                    content=f"ℹ️ 用户取消执行建议 {advice.advice_id[:8]}",
                    info_type=InfoType.USER_ACTION,
                    level=InfoLevel.INFO,
                    source="用户操作"
                )
                advice.status = "rejected"

            # 移除已处理的建议
            if advice.advice_id in self.pending_trading_advice:
                del self.pending_trading_advice[advice.advice_id]

            # 清理临时引用
            self._pending_order_advice = None

        except Exception as e:
            self.logger.error(f"处理订单对话框结果失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            await self.add_info(
                content=f"❌ 订单处理异常: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="订单处理"
            )

    async def _reject_trading_advice(self, advice: TradingAdvice) -> None:
        """拒绝交易建议"""
        try:
            advice.status = "rejected"

            # 删除对应的消息
            removed = await self.remove_info_by_advice_id(advice.advice_id)

            if removed:
                await self.add_info(
                    content=f"❌ 已拒绝并删除建议 {advice.advice_id[:8]}",
                    info_type=InfoType.USER_ACTION,
                    level=InfoLevel.INFO,
                    source="用户操作"
                )
            else:
                await self.add_info(
                    content=f"❌ 已拒绝建议 {advice.advice_id[:8]} (消息未找到)",
                    info_type=InfoType.USER_ACTION,
                    level=InfoLevel.WARNING,
                    source="用户操作"
                )

            # 移除已处理的建议
            del self.pending_trading_advice[advice.advice_id]

        except Exception as e:
            self.logger.error(f"拒绝建议失败: {e}")

    async def _show_advice_detail(self, advice: TradingAdvice) -> None:
        """显示建议详情"""
        try:
            detail_content = [
                f"📊 建议详情 (ID: {advice.advice_id})",
                f"🎯 用户原始需求: {advice.user_prompt}",
                f"📈 目标股票: {advice.stock_code} ({advice.stock_name})",
                f"🎭 推荐操作: {advice.recommended_action}",
                f"⚖️ 风险评估: {advice.risk_assessment}",
                f"🎯 置信度: {advice.confidence_score:.2f}",
                "",
                f"📝 详细分析:",
                advice.detailed_analysis,
                ""
            ]

            if advice.expected_return:
                detail_content.extend([
                    f"💰 预期收益: {advice.expected_return}",
                    ""
                ])

            if advice.suggested_orders:
                detail_content.append("📋 具体订单建议:")
                for i, order in enumerate(advice.suggested_orders, 1):
                    detail_content.append(f"  订单 {i}:")
                    detail_content.append(f"    股票: {order.stock_code}")
                    detail_content.append(f"    操作: {order.action}")
                    detail_content.append(f"    数量: {order.quantity}股")
                    detail_content.append(f"    类型: {order.order_type}")
                    if order.price:
                        detail_content.append(f"    价格: {order.price}元")
                    if order.trigger_price:
                        detail_content.append(f"    触发价: {order.trigger_price}元")
                    if order.reasoning:
                        detail_content.append(f"    原因: {order.reasoning}")
                    detail_content.append("")

            await self.add_info(
                content="\n".join(detail_content),
                info_type=InfoType.TRADE_ADVICE,
                level=InfoLevel.INFO,
                source="建议详情",
                data={
                    'advice_id': advice.advice_id,
                    'full_detail': True
                }
            )

        except Exception as e:
            self.logger.error(f"显示建议详情失败: {e}")
            await self.add_info(
                content=f"详情显示失败: {str(e)}",
                info_type=InfoType.ERROR,
                level=InfoLevel.ERROR,
                source="建议详情"
            )
    
    # AI建议事件处理方法 - 为兼容性保留
    async def on_ai_display_widget_suggestion_accepted(self, event) -> None:
        """处理AI建议被接受事件 - 兼容性方法"""
        try:
            suggestion_id = getattr(event, 'suggestion_id', 'unknown')
            await self.add_info(
                content=f"✅ AI建议已接受: {suggestion_id[:8]}...",
                info_type=InfoType.USER_ACTION,
                level=InfoLevel.INFO,
                source="用户操作"
            )
            self.logger.info(f"用户接受了AI建议: {suggestion_id}")
        except Exception as e:
            self.logger.debug(f"AI建议接受事件处理失败（重构后正常）: {e}")

    async def on_ai_display_widget_suggestion_ignored(self, event) -> None:
        """处理AI建议被忽略事件 - 兼容性方法"""
        try:
            suggestion_id = getattr(event, 'suggestion_id', 'unknown')
            await self.add_info(
                content=f"❌ AI建议已忽略: {suggestion_id[:8]}...",
                info_type=InfoType.USER_ACTION,
                level=InfoLevel.INFO,
                source="用户操作"
            )
            self.logger.info(f"用户忽略了AI建议: {suggestion_id}")
        except Exception as e:
            self.logger.debug(f"AI建议忽略事件处理失败（重构后正常）: {e}")

    async def on_ai_display_widget_suggestion_saved(self, event) -> None:
        """处理AI建议被保存事件 - 兼容性方法"""
        try:
            suggestion_id = getattr(event, 'suggestion_id', 'unknown')
            await self.add_info(
                content=f"💾 AI建议已保存: {suggestion_id[:8]}...",
                info_type=InfoType.USER_ACTION,
                level=InfoLevel.INFO,
                source="用户操作"
            )
            self.logger.info(f"用户保存了AI建议: {suggestion_id}")
        except Exception as e:
            self.logger.debug(f"AI建议保存事件处理失败（重构后正常）: {e}")
    
    async def _start_thinking_animation(self) -> None:
        """启动思考动画"""
        try:
            if not AI_MODULES_AVAILABLE or ThinkingAnimation is None:
                # 如果动画组件不可用，使用静态文本
                await self.add_info(
                    content="🤔 AI正在思考中...",
                    info_type=InfoType.LOG,
                    level=InfoLevel.INFO,
                    source="AI助手"
                )
                return
            
            # 创建思考动画组件
            self.thinking_animation = ThinkingAnimation()
            self.thinking_animation.add_class("log")  # 添加日志样式类
            self.thinking_animation.add_class("info")  # 添加信息级别样式类
            
            # 适配新的双面板结构 - 将动画挂载到消息列表
            try:
                # 尝试新的结构
                container = self.query_one("#info_message_list")
                await container.mount(self.thinking_animation)
            except Exception:
                # 兼容旧结构或降级处理
                self.logger.warning("无法找到消息容器，使用静态文本代替动画")
                await self.add_info(
                    content="🤔 AI正在思考中...",
                    info_type=InfoType.LOG,
                    level=InfoLevel.INFO,
                    source="AI助手"
                )
                return
            
            # 启动动画
            await self.thinking_animation.start_animation()
            
            # 自动滚动到底部
            if self.auto_scroll:
                self.scroll_end(animate=False)
                
        except Exception as e:
            self.logger.error(f"启动思考动画失败: {e}")
            # 降级到静态文本
            await self.add_info(
                content="🤔 AI正在思考中...",
                info_type=InfoType.LOG,
                level=InfoLevel.INFO,
                source="AI助手"
            )
    
    async def _stop_thinking_animation(self) -> None:
        """停止思考动画"""
        try:
            if self.thinking_animation:
                # 停止动画
                await self.thinking_animation.stop_animation()
                
                # 从界面中移除动画组件
                if self.thinking_animation.parent:
                    await self.thinking_animation.remove()
                
                self.thinking_animation = None
                
                self.logger.debug("思考动画已停止并清理")
                
        except Exception as e:
            self.logger.error(f"停止思考动画失败: {e}")


class MessageItem(Vertical):
    """单条消息组件"""

    def __init__(self, message: InfoMessage, **kwargs):
        message_id = f"msg_{id(message)}"
        super().__init__(id=message_id, classes=f"message-item {message.level.value}", **kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        """组合消息组件"""
        # 消息头部
        time_str = self.message.timestamp.strftime("%H:%M:%S")
        type_str = self.message.info_type.value.upper()
        header_text = f"[{time_str}] {type_str}"
        if self.message.source:
            header_text += f" ({self.message.source})"

        yield Static(header_text, classes="message-header")

        # 消息内容（截断长消息）
        content = self.message.content
        if len(content) > 100:
            content = content[:97] + "..."

        yield Static(content, classes="message-content")


class InfoMessageList(ScrollableContainer):
    """信息消息列表组件 - 参考toolong的LogLines"""

    DEFAULT_CSS = """
    InfoMessageList {
        background: $surface;
        height: 1fr;
        width: 1fr;
        overflow-y: auto;
        scrollbar-gutter: stable;
        padding: 1;
    }


    InfoMessageList .message-item {
        height: auto;
        min-height: 3;
        width: 1fr;
        padding: 0 1;
        margin: 0;
        border: solid $border;
        background: $surface;
    }

    InfoMessageList .message-item:hover {
        background: $surface-lighten-1;
    }

    InfoMessageList .message-item.selected {
        background: $primary-darken-1;
        border: solid $accent;
    }

    InfoMessageList .message-item.error {
        border-left: solid $error;
    }

    InfoMessageList .message-item.warning {
        border-left: solid $warning;
    }

    InfoMessageList .message-item.info {
        border-left: solid $success;
    }

    InfoMessageList .message-item.debug {
        border-left: solid $panel;
        opacity: 0.8;
    }

    InfoMessageList .message-header {
        height: 1;
        text-style: bold;
    }

    InfoMessageList .message-content {
        height: 1;
        color: $text-muted;
        text-wrap: wrap;
    }
    """

    class MessageSelected(Message):
        """消息选择事件"""
        def __init__(self, message: InfoMessage):
            super().__init__()
            self.message = message

    def __init__(self, buffer: InfoBuffer, **kwargs):
        """初始化消息列表"""
        super().__init__(**kwargs)
        self.buffer = buffer
        self.selected_message: Optional[InfoMessage] = None
        self.message_widgets: Dict[str, Widget] = {}
        self.logger = get_logger("info_message_list")

    def compose(self) -> ComposeResult:
        """组合消息列表"""
        with Vertical():
            yield Static("暂无消息", classes="empty-state", id="empty_state")

    async def refresh_messages(self, filtered_messages: List[InfoMessage]) -> None:
        """刷新消息列表"""
        try:
            # 清空现有消息组件
            await self.query(".message-item").remove()
            self.message_widgets.clear()

            empty_state = self.query_one("#empty_state")

            if filtered_messages:
                empty_state.display = False

                # 只显示最新的消息（限制数量避免性能问题）
                display_messages = filtered_messages[-100:]  # 最多显示100条

                for message in display_messages:
                    message_id = f"msg_{id(message)}"
                    message_widget = MessageItem(message)
                    self.message_widgets[message_id] = message_widget
                    await self.mount(message_widget)

                self.logger.debug(f"刷新消息列表: {len(display_messages)} 条消息")
            else:
                empty_state.display = True

            # 滚动到底部显示最新消息
            self.scroll_end(animate=True)

        except Exception as e:
            self.logger.error(f"刷新消息列表失败: {e}")


    async def on_click(self, event) -> None:
        """处理点击事件"""
        # 寻找被点击的消息项
        clicked_widget = event.widget
        while clicked_widget and not clicked_widget.classes or "message-item" not in clicked_widget.classes:
            clicked_widget = clicked_widget.parent
            if not clicked_widget:
                return

        # 找到对应的消息
        message_id = clicked_widget.id
        if message_id in self.message_widgets:
            widget = self.message_widgets[message_id]
            # 获取对应的消息对象
            for message in self.buffer.messages:
                if f"msg_{id(message)}" == message_id:
                    await self.select_message(message, widget)
                    break

    async def select_message(self, message: InfoMessage, widget: Widget) -> None:
        """选择消息"""
        # 更新选中状态
        if self.selected_message:
            # 移除之前选中项的选中样式
            for msg_widget in self.message_widgets.values():
                msg_widget.remove_class("selected")

        # 添加新选中项的样式
        widget.add_class("selected")
        self.selected_message = message

        # 发送选择事件
        self.post_message(self.MessageSelected(message))

        self.logger.info(f"选中消息: {message.content[:50]}...")

    async def select_last_message(self) -> bool:
        """选择最后一条消息并滚动到底部

        Returns:
            bool: 是否成功选择
        """
        try:
            if not self.message_widgets:
                return False

            # 获取最后一条消息
            if not self.buffer.messages:
                return False

            last_message = self.buffer.messages[-1]
            message_id = f"msg_{id(last_message)}"

            if message_id in self.message_widgets:
                widget = self.message_widgets[message_id]
                await self.select_message(last_message, widget)
                # 确保滚动到底部
                self.scroll_end(animate=True)
                return True

            return False
        except Exception as e:
            self.logger.error(f"选择最后一条消息失败: {e}")
            return False


class InfoDetailView(ScrollableContainer):
    """信息详情视图组件 - 参考toolong的LinePanel"""

    DEFAULT_CSS = """
    InfoDetailView {
        background: $panel;
        height: 1fr;
        width: 1fr;
        overflow-y: auto;
        padding: 1;
    }


    InfoDetailView .detail-header {
        height: auto;
        padding: 0 0 1 0;
        text-style: bold;
        border-bottom: solid $border;
        margin-bottom: 1;
    }

    InfoDetailView .detail-section {
        height: auto;
        padding: 1 0;
        margin: 1 0;
    }

    InfoDetailView .detail-content {
        height: auto;
        padding: 1;
        background: $surface;
        border: solid $border;
        margin: 1 0;
    }

    InfoDetailView .detail-metadata {
        height: auto;
        color: $text-muted;
        border-top: solid $border;
        padding: 1 0 0 0;
        margin-top: 1;
    }

    InfoDetailView .trading-actions {
        height: auto;
        padding: 1;
        margin: 1 0;
        border: solid $primary;
        background: rgba(0, 100, 200, 0.1);
    }

    InfoDetailView .action-button {
        margin: 0 1 1 0;
        min-width: 12;
    }

    InfoDetailView .confirm-button {
        background: $success;
        color: $text;
    }

    InfoDetailView .reject-button {
        background: $error;
        color: $text;
    }
    """

    class TradingActionRequested(Message):
        """交易操作请求消息"""
        def __init__(self, action: str, advice_id: str):
            super().__init__()
            self.action = action  # 'confirm', 'reject'
            self.advice_id = advice_id

    def __init__(self, **kwargs):
        """初始化详情视图"""
        super().__init__(**kwargs)
        self.current_message: Optional[InfoMessage] = None
        self.logger = get_logger("info_detail_view")

    def compose(self) -> ComposeResult:
        """组合详情视图"""
        with Vertical():
            yield Static("选择左侧消息查看详细信息", classes="detail-content", id="empty_detail")

    async def update_detail(self, message: InfoMessage) -> None:
        """更新详情显示"""
        try:
            self.current_message = message

            # 清空当前内容
            await self.query("*").remove()

            with self.app.batch_update():
                # 标题
                level_icon = self._get_level_icon(message.level)
                type_icon = self._get_type_icon(message.info_type)
                title = f"{level_icon} {type_icon} {message.info_type.value.upper()}"
                await self.mount(Static(title, classes="detail-header"))

                # 消息内容
                await self.mount(Static("消息内容:", classes="detail-section"))
                await self.mount(Static(message.content, classes="detail-content"))

                # 如果是AI交易建议消息，添加操作按钮
                if message.info_type == InfoType.TRADE_ADVICE and message.data:
                    await self._add_trading_action_buttons(message)

                # 如果有附加数据，显示为JSON
                if message.data:
                    try:
                        await self.mount(Static("附加数据:", classes="detail-section"))
                        json_content = JSON.from_data(message.data)
                        await self.mount(Static(json_content, classes="detail-content"))
                    except Exception:
                        await self.mount(Static(f"数据: {str(message.data)}", classes="detail-content"))

                # 元数据
                metadata_text = self._format_metadata(message)
                await self.mount(Static(metadata_text, classes="detail-metadata"))

            self.logger.info(f"更新消息详情: {message.content[:50]}...")

        except Exception as e:
            self.logger.error(f"更新详情显示失败: {e}")

    async def _add_trading_action_buttons(self, message: InfoMessage) -> None:
        """为AI交易建议添加操作按钮"""
        try:
            advice_id = message.data.get('advice_id')
            if not advice_id:
                return

            # 添加操作区域标题
            await self.mount(Static("🎛️ 快捷操作:", classes="detail-section"))

            # 创建按钮容器
            button_container = Horizontal(classes="trading-actions")
            await self.mount(button_container)

            # 在容器中添加按钮
            confirm_btn = Button(
                "✅ 确认执行",
                id=f"confirm_{advice_id}",
                classes="action-button confirm-button"
            )
            await button_container.mount(confirm_btn)

            reject_btn = Button(
                "❌ 拒绝建议",
                id=f"reject_{advice_id}",
                classes="action-button reject-button"
            )
            await button_container.mount(reject_btn)

            # 添加操作说明
            help_text = [
                "💡 操作说明:",
                "• 确认执行：弹出订单对话框确认执行",
                "• 拒绝建议：拒绝此建议并删除消息"
            ]
            await self.mount(Static("\n".join(help_text), classes="detail-content"))

            self.logger.info(f"为建议 {advice_id[:8]} 添加操作按钮")

        except Exception as e:
            self.logger.error(f"添加交易操作按钮失败: {e}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理按钮点击事件"""
        try:
            button_id = event.button.id
            if not button_id:
                return

            # 解析按钮ID获取操作类型和建议ID
            if button_id.startswith(('confirm_', 'reject_')):
                action = button_id.split('_')[0]
                advice_id = button_id[len(action) + 1:]

                self.logger.info(f"用户点击 {action} 操作，建议ID: {advice_id[:8]}")

                # 发送操作请求消息
                self.post_message(self.TradingActionRequested(action, advice_id))

        except Exception as e:
            self.logger.error(f"处理按钮点击事件失败: {e}")

    def _get_level_icon(self, level: InfoLevel) -> str:
        """获取级别图标"""
        level_icons = {
            InfoLevel.DEBUG: "🔍",
            InfoLevel.INFO: "ℹ️",
            InfoLevel.WARNING: "⚠️",
            InfoLevel.ERROR: "❌",
            InfoLevel.CRITICAL: "🚨",
        }
        return level_icons.get(level, "•")

    def _get_type_icon(self, info_type: InfoType) -> str:
        """获取类型图标"""
        type_icons = {
            InfoType.LOG: "📝",
            InfoType.STOCK_DATA: "📈",
            InfoType.TRADE_INFO: "💰",
            InfoType.PERFORMANCE: "⚡",
            InfoType.API_STATUS: "🔗",
            InfoType.USER_ACTION: "👤",
            InfoType.ERROR: "❌",
            InfoType.WARNING: "⚠️",
        }
        return type_icons.get(info_type, "•")

    def _format_metadata(self, message: InfoMessage) -> str:
        """格式化元数据"""
        metadata = []

        # 基本信息
        metadata.append(f"消息ID: {id(message)}")
        metadata.append(f"消息类型: {message.info_type.value}")
        metadata.append(f"消息级别: {message.level.value}")
        metadata.append(f"时间戳: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")

        if message.source:
            metadata.append(f"消息源: {message.source}")

        # 消息统计
        metadata.append(f"内容长度: {len(message.content)} 字符")

        if message.data:
            metadata.append(f"附加数据: {len(str(message.data))} 字符")

        return "\n".join(metadata)


# 向后兼容的类名
LinePanel = InfoPanel
LineDisplay = InfoDisplay