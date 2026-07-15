"""
Monitor UI Layout Module
基于 Textual 框架的监控界面布局组件
参考: https://textual.textualize.io/guide/layout/
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Grid, Horizontal
from textual.widgets import (
    Static, DataTable, Label, 
    TabbedContent, TabPane, ProgressBar
)
from textual.reactive import reactive
from textual.binding import Binding
from typing import List, Dict, Optional
import asyncio
from ..utils.global_vars import get_logger

STOCK_COLUMNS = {
            "code": {"label": "代码", "width": 12},
            "name": {"label": "名称", "width": 10},
            "price": {"label": "价格", "width": 10},
            "change": {"label": "涨跌", "width": 10},
            "volume": {"label": "成交量", "width": 10},
            "time": {"label": "时间", "width": 10},
        }


class StockListPanel(Container):
    """股票列表面板 - 左侧50%区域"""
    
    DEFAULT_CSS = """
    StockListPanel {
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
    }
    
    StockListPanel DataTable {
        height: 1fr;
        
        padding: 1;
    }
    
    StockListPanel DataTable > .datatable--header {
        
        height: 3;
        padding: 1;
    }
    
    StockListPanel DataTable > .datatable--body {
        
        padding: 1;
    }
    
    StockListPanel DataTable > .datatable--row {
        height: 3;
        padding: 0 1;
    }
    
    StockListPanel .button-bar {
        height: 3;
        dock: bottom;
        background: $surface;
        text-align: center;
        
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "监控股票列表"
        
    def compose(self) -> ComposeResult:
        """组合股票列表组件"""
        # 股票数据表格
        stock_table = DataTable(
            show_cursor=True,
            zebra_stripes=True,
            cursor_type="row",
            show_header=True,
            show_row_labels=False,
            id="stock_table"
        )
        # 添加表格列
        for column_key, column_data in STOCK_COLUMNS.items():
            column_width = column_data["width"]
            column_label = column_data["label"]
            stock_table.add_column(column_label, key=column_key, width=column_width)
        yield stock_table
        
        # 快捷键提示区域
        with Container(classes="button-bar"):
            yield Static(
                "[bold green]N[/bold green] 添加  [bold red]K[/bold red] 删除  [bold yellow]Space[/bold yellow] 菜单  [bold blue]O[/bold blue] 订单  [bold magenta]T[/bold magenta] 切换模式  [bold white]I[/bold white] AI",
                id="hotkey_hints"
            )


class UserGroupPanel(Container):
    """用户分组面板 - 右侧50%区域（完全合并的单一窗口）"""
    
    DEFAULT_CSS = """
    UserGroupPanel {
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 1;
        layout: horizontal;
    }
    
    UserGroupPanel .group-table-area {
        width: 30%;
        height: 1fr;
        background: $surface;
        overflow-y: auto;
        padding: 1;
        margin-right: 1;
    }

    UserGroupPanel .group-table-area DataTable {
        height: 1fr;
        margin-bottom: 1;
    }

    UserGroupPanel .position-info {
        width: 70%;
        height: 1fr;
        background: $surface;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 1;
        layout: vertical;
        overflow-y: auto;
    }

    UserGroupPanel .position-table-top {
        width: 1fr;
        height: 1fr;
        min-height: 8;
        margin-bottom: 1;
    }

    UserGroupPanel .position-table-top DataTable {
        height: 1fr;
        min-height: 6;
    }

    UserGroupPanel .orders-table-bottom {
        width: 1fr;
        height: 1fr;
        min-height: 6;
    }

    UserGroupPanel .orders-table-bottom DataTable {
        height: 1fr;
    }

    UserGroupPanel DataTable {
        height: 1fr;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "分组与股票管理"
        
    def compose(self) -> ComposeResult:
        """组合完全统一的单一窗口"""
        # 分组表格区域（50%空间）
        with Container(classes="group-table-area"):
            # 分组表格
            group_table = DataTable(
                show_cursor=True,
                zebra_stripes=True,
                cursor_type="row",
                show_header=True,
                show_row_labels=False,
                id="group_table"
            )
            group_table.add_columns("分组名称", "股票数量", "类型")
            yield group_table

            # 交易模式显示
            yield Static(
                "[bold yellow]🔄 当前交易模式: 模拟交易[/bold yellow]",
                id="trading_mode_display"
            )

        # 持仓订单信息区域（70%空间）
        with Container(classes="position-info"):
            # 上部：持仓信息表格（40%高度）
            with Container(classes="position-table-top"):
                # 创建持仓信息表格
                position_table = DataTable(
                    show_cursor=True,
                    zebra_stripes=True,
                    cursor_type="row",
                    show_header=True,
                    show_row_labels=False,
                    id="position_table"
                )
                position_table.add_columns("股票代码", "股票名称", "持仓数量", "可卖数量", "成本价", "当前价", "盈亏", "盈亏比例")
                yield position_table

            # 下部：订单信息表格（60%高度）
            with Container(classes="orders-table-bottom"):
                yield Static("[bold cyan]订单信息[/bold cyan]", id="orders_title")
                # 创建订单信息表格
                orders_table = DataTable(
                    show_cursor=True,
                    zebra_stripes=True,
                    cursor_type="row",
                    show_header=True,
                    show_row_labels=False,
                    id="orders_table"
                )
                orders_table.add_columns("订单号", "股票", "类型", "状态", "价格", "数量")
                yield orders_table




class AnalysisPanel(Container):
    """分析面板 - 严格按照MVP设计的完整实现"""
    
    BINDINGS = [
        Binding("z", "return_to_main", "返回主界面", priority=True),
    ]
    
    def __init__(self, **kwargs):
        """初始化分析面板"""
        super().__init__(**kwargs)
        self._app_ref = None
        self._basic_info_widget = None
        self._tabbed_content = None
        self._kline_chart_widget = None
        self.logger = get_logger(__name__)
        
        # 实时更新相关
        self._realtime_update_task: Optional[asyncio.Task] = None
        self._realtime_update_interval: int = 3  # 秒
        
    def set_app_reference(self, app):
        """设置应用引用以访问数据管理器"""
        self._app_ref = app
        
    def get_analysis_data_manager(self):
        """获取分析数据管理器"""
        if self._app_ref and hasattr(self._app_ref, 'app_core'):
            return getattr(self._app_ref.app_core, 'analysis_data_manager', None)
        return None
    
    def get_refresh_mode(self) -> str:
        """获取当前刷新模式"""
        try:
            if self._app_ref and hasattr(self._app_ref, 'app_core'):
                return getattr(self._app_ref.app_core, 'refresh_mode', '快照模式')
            return '快照模式'
        except Exception:
            return '快照模式'
    
    def is_realtime_mode(self) -> bool:
        """判断是否为实时模式"""
        refresh_mode = self.get_refresh_mode()
        return '实时' in refresh_mode
    
    async def start_realtime_updates(self):
        """启动实时数据更新"""
        if self._realtime_update_task and not self._realtime_update_task.done():
            return  # 已经在运行
        
        if not self.is_realtime_mode():
            return  # 非实时模式，不启动
        
        self._realtime_update_task = asyncio.create_task(self._realtime_update_loop())
        self.logger.info("已启动分析面板实时数据更新")
    
    async def stop_realtime_updates(self):
        """停止实时数据更新"""
        if self._realtime_update_task and not self._realtime_update_task.done():
            self._realtime_update_task.cancel()
            try:
                await self._realtime_update_task
            except asyncio.CancelledError:
                pass
            self.logger.info("已停止分析面��实时数据更新")
    
    async def _realtime_update_loop(self):
        """实时数据更新循环"""
        broker_update_counter = 0
        broker_update_interval = 3  # 每3个周期更新一次经纪队列
        
        while True:
            try:
                # 检查是否仍为实时模式
                if not self.is_realtime_mode():
                    self.logger.info("切换到非实时模式，停止实时更新")
                    break
                
                # 检查是否有数据管理器和当前股票
                data_manager = self.get_analysis_data_manager()
                if not data_manager or not data_manager.current_stock_code:
                    await asyncio.sleep(self._realtime_update_interval)
                    continue
                
                # 更新高频数据
                await self.update_basic_info()
                await self.update_quote_info()
                await self.update_orderbook_data()
                await self.update_tick_data()
                await self.update_capital_flow()
                
                # 低频更新经纪队列数据
                broker_update_counter += 1
                if broker_update_counter >= broker_update_interval:
                    await self.update_broker_queue()
                    broker_update_counter = 0
                
                await asyncio.sleep(self._realtime_update_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"实时数据更新错误: {e}")
                await asyncio.sleep(self._realtime_update_interval)
    
    async def update_quote_info(self):
        """更新实时报价信息（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 注意：quote_info_content已改为kline_chart_content，报价信息已统一在基础信息中显示
            # 这个方法现在不需要单独更新报价信息
            pass
                
        except Exception as e:
            self.logger.error(f"更新报价信息失败: {e}")
    
    async def update_orderbook_data(self):
        """更新五档买卖盘数据（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 使用data_manager的格式化方法
            formatted_orderbook = data_manager.format_orderbook_data(analysis_data)
            
            # 检测变化并应用闪烁效果
            flash_value, needs_flash = data_manager.get_formatted_data_with_flash(
                data_manager.current_stock_code, 'orderbook', formatted_orderbook
            )
            
            orderbook_widget = self.query_one("#order_book_content", expect_type=None)
            if orderbook_widget and hasattr(orderbook_widget, 'update'):
                if needs_flash:
                    # 立即应用闪烁样式
                    orderbook_widget.update(flash_value)
                    # 创建恢复任务
                    await data_manager.create_flash_restore_task(orderbook_widget, formatted_orderbook, 0.5)
                else:
                    # 直接更新正常样式
                    orderbook_widget.update(formatted_orderbook)
                
        except Exception as e:
            self.logger.error(f"更新五档数据失败: {e}")
    
    async def update_tick_data(self):
        """更新逐笔交易数据（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 使用data_manager的格式化方法
            formatted_tick = data_manager.format_tick_data(analysis_data)
            
            # 检测变化并应用闪烁效果
            flash_value, needs_flash = data_manager.get_formatted_data_with_flash(
                data_manager.current_stock_code, 'tick', formatted_tick
            )
            
            tick_widget = self.query_one("#tick_content", expect_type=None)
            if tick_widget and hasattr(tick_widget, 'update'):
                if needs_flash:
                    # 立即应用闪烁样式
                    tick_widget.update(flash_value)
                    # 创建恢复任务
                    await data_manager.create_flash_restore_task(tick_widget, formatted_tick, 0.5)
                else:
                    # 直接更新正常样式
                    tick_widget.update(formatted_tick)
                
        except Exception as e:
            self.logger.error(f"更新逐笔数据失败: {e}")
    
    async def update_broker_queue(self):
        """更新经纪队列数据（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 使用data_manager的格式化方法
            formatted_broker = data_manager.format_broker_queue(analysis_data)
            
            # 检测变化并应用闪烁效果
            flash_value, needs_flash = data_manager.get_formatted_data_with_flash(
                data_manager.current_stock_code, 'broker', formatted_broker
            )
            
            broker_widget = self.query_one("#broker_content", expect_type=None)
            if broker_widget and hasattr(broker_widget, 'update'):
                if needs_flash:
                    # 立即应用闪烁样式
                    broker_widget.update(flash_value)
                    # 创建恢复任务
                    await data_manager.create_flash_restore_task(broker_widget, formatted_broker, 0.5)
                else:
                    # 直接更新正常样式
                    broker_widget.update(formatted_broker)
                
        except Exception as e:
            self.logger.error(f"更新经纪队列失败: {e}")
    
    async def update_capital_flow(self):
        """更新资金流向数据（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 使用data_manager的异步格式化方法
            formatted_capital = await data_manager.format_capital_flow(analysis_data)
            
            # 检测变化并应用闪烁效果
            flash_value, needs_flash = data_manager.get_formatted_data_with_flash(
                data_manager.current_stock_code, 'capital', formatted_capital
            )
            
            capital_widget = self.query_one("#money_flow_content_column", expect_type=None)
            if capital_widget and hasattr(capital_widget, 'update'):
                if needs_flash:
                    # 立即应用闪烁样式
                    capital_widget.update(flash_value)
                    # 创建恢复任务
                    await data_manager.create_flash_restore_task(capital_widget, formatted_capital, 0.5)
                else:
                    # 直接更新正常样式
                    capital_widget.update(formatted_capital)
                
        except Exception as e:
            self.logger.error(f"更新资金流向失败: {e}")
        
    async def update_basic_info(self):
        """更新基础信息显示（带闪烁效果）"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                if self._basic_info_widget:
                    self._basic_info_widget.update("等待数据管理器初始化...")
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                return
                
            # 使用data_manager的格式化方法
            formatted_info = data_manager.format_basic_info(analysis_data)
            
            # 检测变化并应用闪烁效果
            flash_value, needs_flash = data_manager.get_formatted_data_with_flash(
                data_manager.current_stock_code, 'basic_info', formatted_info
            )
            
            if self._basic_info_widget:
                if needs_flash:
                    # 立即应用闪烁样式
                    self._basic_info_widget.update(flash_value)
                    # 创建恢复任务
                    await data_manager.create_flash_restore_task(self._basic_info_widget, formatted_info, 0.5)
                else:
                    # 直接更新正常样式
                    self._basic_info_widget.update(formatted_info)
                    
        except Exception as e:
            if self._basic_info_widget:
                self._basic_info_widget.update(f"数据加载错误: {str(e)}")
            self.logger.error(f"更新基础信息失败: {e}")

    async def update_kline_chart(self):
        """更新K线图数据"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                self.logger.warning("data_manager 为空，无法更新K线图")
                return
            if not self._kline_chart_widget:
                self.logger.warning("_kline_chart_widget 为空，无法更新K线图")
                return
                
            analysis_data = data_manager.get_current_analysis_data()
            if not analysis_data:
                self.logger.warning("analysis_data 为空，无法更新K线图")
                return
            if not analysis_data.kline_data:
                self.logger.warning("analysis_data.kline_data 为空，无法更新K线图")
                return
                
            # 打印调试信息
            self.logger.info(f"准备更新K线图: stock_code={data_manager.current_stock_code}, "
                           f"time_period={data_manager.current_time_period}, "
                           f"kline_data_count={len(analysis_data.kline_data)}")
            
            # 更新K线图
            self._kline_chart_widget.set_stock(
                data_manager.current_stock_code or "",
                data_manager.current_time_period or "D"
            )
            self._kline_chart_widget.update_data(analysis_data.kline_data)
            self.logger.info("K线图数据更新完成")
            
        except Exception as e:
            self.logger.error(f"更新K线图失败: {e}")
            import traceback
            self.logger.error(f"详细错误堆栈: {traceback.format_exc()}")

    async def update_data(self):
        """更新信息"""
        try:
            await self.update_basic_info()
            await self.update_quote_info()
            await self.update_orderbook_data()
            await self.update_tick_data()
            await self.update_broker_queue()
            await self.update_capital_flow()
            await self.update_kline_chart()
                
        except Exception as e:
            if self._basic_info_widget:
                self._basic_info_widget.update(f"数据加载错误: {str(e)}")
            self.logger.error(f"更新信息: {e}")
    
    async def on_stock_changed(self, stock_code: str):
        """处理股票切换事件"""
        try:
            data_manager = self.get_analysis_data_manager()
            if not data_manager:
                return
                
            # 设置当前分析的股票并加载数据
            success = await data_manager.set_current_stock(stock_code)
            if success:
                # 更新基础信息显示
                await self.update_data()
                
                # 重新启动实时更新（如果在实时模式）
                await self.stop_realtime_updates()
                await self.start_realtime_updates()
            else:
                if self._basic_info_widget:
                    self._basic_info_widget.update(f"加载股票 {stock_code} 数据失败")
                    
        except Exception as e:
            if self._basic_info_widget:
                self._basic_info_widget.update(f"股票切换错误: {str(e)}")
    
    
    async def on_mount(self) -> None:
        """组件挂载时初始化"""
        #self.logger.debug(f"DEBUG: AnalysisPanel on_mount 开始，组件ID: {self.id}")
        
        # 尝试初始加载数据
        await self.update_data()
        
        # 获取 TabbedContent 组件引用
        try:
            self._tabbed_content = self.query_one("#realtime_tabs", TabbedContent)
            #self.logger.debug(f"DEBUG: 成功找到 TabbedContent: {self._tabbed_content}")
        except Exception as e:
            #self.logger.debug(f"DEBUG: 未找到 TabbedContent: {e}")
            self._tabbed_content = None
        
        # 获取K线图组件引用
        try:
            self.logger.info("开始查找K线图组件 #kline_chart_widget")
            all_widgets = list(self.query("*"))
            self.logger.info(f"当前所有子组件: {[w.id if hasattr(w, 'id') and w.id else str(type(w).__name__) for w in all_widgets]}")
            
            self._kline_chart_widget = self.query_one("#kline_chart_widget")
            self.logger.info(f"成功找到K线图组件: {self._kline_chart_widget}")
        except Exception as e:
            self.logger.warning(f"未找到K线图组件: {e}")
            # 尝试按类型查找
            try:
                from .widgets.kline_chart import KLineChartWidget
                kline_widgets = list(self.query(KLineChartWidget))
                if kline_widgets:
                    self._kline_chart_widget = kline_widgets[0]
                    self.logger.info(f"通过类型找到K线图组件: {self._kline_chart_widget}")
                else:
                    self.logger.warning("通过类型也未找到K线图组件")
                    self._kline_chart_widget = None
            except Exception as e2:
                self.logger.error(f"按类型查找K线图组件也失败: {e2}")
                self._kline_chart_widget = None
        
            
        # 设置焦点，确保能接收键盘事件
        self.can_focus = True
        #self.logger.debug(f"DEBUG: AnalysisPanel 设置 can_focus=True")
        
        # 立即获取焦点
        self.focus()
        #self.logger.debug(f"DEBUG: AnalysisPanel 调用 focus()，当前焦点状态: {self.has_focus}")
        
        # 延迟再次确认焦点状态
        def ensure_focus():
            #self.logger.debug(f"DEBUG: 延迟检查焦点状态: {self.has_focus}")
            if not self.has_focus:
                self.logger.debug("DEBUG: 焦点丢失，重新获取焦点")
                self.focus()
                #self.logger.debug(f"DEBUG: 重新获取焦点后状态: {self.has_focus}")
            else:
                self.logger.debug("DEBUG: 焦点状态正常")
        
        self.call_after_refresh(ensure_focus)
        self.logger.debug("DEBUG: AnalysisPanel 设置焦点完成")
        
        # 启动实时更新（如果在实时模式）
        await self.start_realtime_updates()
    
    async def on_unmount(self) -> None:
        """组件卸载时清理"""
        await self.stop_realtime_updates()
        self.logger.debug("AnalysisPanel 卸载完成")
    
    async def on_refresh_mode_changed(self):
        """当刷新模式改变时调用"""
        if self.is_realtime_mode():
            # 切换到实时模式，启动实时更新
            await self.start_realtime_updates()
        else:
            # 切换到快照模式，停止实时更新
            await self.stop_realtime_updates()
    
    def _ensure_focus_after_switch(self) -> None:
        """标签页切换后确保获得焦点"""
        def ensure_focus():
            try:
                # 找到当前活跃标签页中的AnalysisPanel
                main_tabs = self.app.query_one("#main_tabs", TabbedContent)
                current_tab_id = main_tabs.active
                #self.logger.debug(f"DEBUG: 焦点恢复 - 当前活跃标签页: {current_tab_id}")
                
                # 如果当前是主界面标签页，不需要设置AnalysisPanel焦点
                if current_tab_id == "main":
                    self.logger.debug("DEBUG: 当前在主界面，无需设置AnalysisPanel焦点")
                    return
                
                # 只有分析标签页才需要设置AnalysisPanel焦点
                if current_tab_id.startswith('analysis_'):
                    # 查找当前标签页中的AnalysisPanel
                    try:
                        # 直接查找当前标签页的AnalysisPanel
                        current_panel = main_tabs.query_one(f"#{current_tab_id} AnalysisPanel")
                        current_panel.focus()
                        #self.logger.debug(f"DEBUG: 为当前标签页的AnalysisPanel设置焦点，焦点状态: {current_panel.has_focus}")
                    except Exception as e:
                        # 备用方案：找到所有AnalysisPanel并设置第一个
                        analysis_panels = self.app.query("AnalysisPanel")
                        if analysis_panels:
                            analysis_panels[0].focus()
                            #self.logger.debug(f"DEBUG: 备用方案设置焦点成功")
                        
            except Exception as e:
                pass
                #self.logger.debug(f"DEBUG: 切换后设置焦点失败: {e}")
        
        # 延迟执行以确保标签页切换完成
        self.call_after_refresh(ensure_focus)
    
    def on_click(self, event) -> None:
        """处理点击事件，确保获得焦点"""
        #self.logger.debug(f"DEBUG: AnalysisPanel 被点击，当前焦点状态: {self.has_focus}")
        self.focus()
        #self.logger.debug(f"DEBUG: 点击后重新设置焦点，焦点状态: {self.has_focus}")
    
    def on_key(self, event) -> None:
        """处理所有键盘事件"""
        # 只有当前获得焦点的AnalysisPanel才处理事件，防止重复执行
        if not self.has_focus:
            return
            
        #self.logger.debug(f"DEBUG: AnalysisPanel 收到按键事件: {event.key}, 焦点状态: {self.has_focus}")
        
        # K线图相关快捷键
        if self._kline_chart_widget and event.key in ['left', 'right', 'up', 'down', 'home', 'end', 'v']:
            try:
                # 将按键事件传递给K线图组件
                action_map = {
                    'left': 'scroll_left',
                    'right': 'scroll_right', 
                    'up': 'zoom_in',
                    'down': 'zoom_out',
                    'home': 'jump_start',
                    'end': 'jump_end',
                    'v': 'toggle_volume'
                }
                action_name = action_map.get(event.key)
                if action_name and hasattr(self._kline_chart_widget, f'action_{action_name}'):
                    getattr(self._kline_chart_widget, f'action_{action_name}')()
                    event.prevent_default()
                    return
            except Exception as e:
                self.logger.error(f"K线图按键处理错误: {e}")
        
        # 时间周期切换快捷键
        if event.key.upper() in ['U', 'J', 'M']:
            try:
                period_map = {'U': 'D', 'J': 'W', 'M': 'M'}
                new_period = period_map[event.key.upper()]
                asyncio.create_task(self.switch_time_period(new_period))
                event.prevent_default()
                return
            except Exception as e:
                self.logger.error(f"时间周期切换错误: {e}")
        
        if event.key == "z":
            #self.logger.debug("DEBUG: z键被按下，返回主界面")
            self.action_return_to_main()
            event.prevent_default()
        else:
            pass
            #self.logger.debug(f"DEBUG: AnalysisPanel 未处理的按键: {event.key}")
    
    async def switch_time_period(self, period: str):
        """切换K线时间周期"""
        try:
            data_manager = self.get_analysis_data_manager()
            if data_manager:
                # 切换时间周期并重新加载数据
                await data_manager.change_time_period(period)
                
                # 更新K线图显示
                await self.update_kline_chart()
                
                # 显示切换信息
                period_names = {'D': '日线', 'W': '周线', 'M': '月线'}
                self.logger.info(f"已切换到{period_names.get(period, period)}")
                
        except Exception as e:
            self.logger.error(f"切换时间周期失败: {e}")
    
    def action_return_to_main(self) -> None:
        """返回主界面（z键）"""
        try:
            # 获取主标签页容器
            main_tabs = self.app.query_one("#main_tabs", TabbedContent)
            main_tabs.active = "main"
            self.logger.debug("DEBUG: 已返回主界面")
        except Exception:
            pass
            #self.logger.debug("DEBUG: 返回主界面失败")
    
    
    DEFAULT_CSS = """
    AnalysisPanel {
        height: 1fr;
        layout: vertical;
        overflow-y: auto;
    }
    
    AnalysisPanel .basic-info-area {
        height: 6%;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 0;
        margin-bottom: 0;
    }
    
    AnalysisPanel .kline-area {
        height: 50%;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 0;
        margin-bottom: 0;
    }
    
    AnalysisPanel .three-column-area {
        height: 45%;
        layout: horizontal;
        margin-bottom: 0;
    }
    
    AnalysisPanel .order-book-column {
        width: 24%;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 0;
        margin-right: 0;
    }
    
    AnalysisPanel .realtime-data-column {
        width: 37%;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 0;
        margin-right: 0;
    }
    
    AnalysisPanel .money-flow-column {
        width: 39%;
        border: solid $accent;
        border-title-color: $text;
        border-title-background: $surface;
        padding: 0;
        layout: vertical;
    }
    
    AnalysisPanel .realtime-data-column TabbedContent {
        height: 1fr;
    }

    AnalysisPanel .realtime-data-column TabPane {
        padding: 0;
    }

    AnalysisPanel .data-content-horizontal {
        layout: horizontal;
        height: 1fr;
    }

    AnalysisPanel .data-content-horizontal Static {
        width: 1fr;
        margin-right: 1;
    }
    """
    
    def compose(self) -> ComposeResult:
        """严格按照MVP设计组合分析面板的完整布局"""
        # 1. 基础信息区域
        with Container(classes="basic-info-area"):
            basic_info_widget = Static(
                "等待股票数据加载...",
                id="basic_info_content"
            )
            self._basic_info_widget = basic_info_widget
            yield basic_info_widget
        
        # 2. K线图区域  
        with Container(classes="kline-area"):
            # 导入并创建K线图组件
            from .widgets.kline_chart import KLineChartWidget
            yield KLineChartWidget(
                stock_code="",
                time_period="D",
                id="kline_chart_widget"
            )
        
        # 3. 三栏布局区域
        with Container(classes="three-column-area"):
            # 3.1 摆盘区域（25%宽度）
            with Container(classes="order-book-column"):
                yield Static("摆盘区域", id="order_book_title")
                yield Static(
                    "[bold red]卖五: 12.89  1250手[/bold red]\n" +
                    "[bold red]卖四: 12.88  2100手[/bold red]\n" +
                    "[bold red]卖三: 12.87  3400手[/bold red]\n" +
                    "[bold red]卖二: 12.86  4200手[/bold red]\n" +
                    "[bold red]卖一: 12.85  5800手[/bold red]\n" +
                    "──────────────────\n" +
                    "[bold green]买一: 12.84  6200手[/bold green]\n" +
                    "[bold green]买二: 12.83  4900手[/bold green]\n" +
                    "[bold green]买三: 12.82  3100手[/bold green]\n" +
                    "[bold green]买四: 12.81  2800手[/bold green]\n" +
                    "[bold green]买五: 12.80  1900手[/bold green]\n\n" +
                    "📈 委比: +8.2%\n" +
                    "📊 委差: +1.8万手",
                    id="order_book_content"
                )
            
            # 3.2 实时数据区域（37%宽度）
            with Container(classes="realtime-data-column"):
                yield Static("实时数据区域", id="realtime_data_title")
                # 水平布局容器包含逐笔数据和经纪队列
                with Horizontal(classes="data-content-horizontal"):
                    # 逐笔数据（50%宽度）
                    yield Static(
                                "[bold yellow]逐笔数据[/bold yellow]\n" +
                                "14:32:15  12.85↑125  89手\n" +
                                "14:32:18  12.84↓89   45手\n" +
                                "14:32:20  12.85↑201  156手\n" +
                                "14:32:22  12.86↑67   67手",
                                id="tick_content"
                            )
                        
                        # 经纪队列数据（50%宽度）
                    yield Static(
                                "[bold cyan]经纪队列[/bold cyan]\n" +
                                "中信证券 买入排队 1.2万手\n" +
                                "平安证券 卖出排队 8.9千手\n" +
                                "招商证券 买入排队 6.8千手",
                                id="broker_content"
                            )
            
            # 3.3 资金流向区域（38%宽度） 
            with Container(classes="money-flow-column"):
                yield Static("资金流向/分布区域", id="money_flow_title")
                yield Static(
                    "主力净流入: +2.3亿 ↑    超大单: +1.8亿(+3.2%)    大单: +0.5亿(+0.9%)    中单: -1.2亿(-2.1%)    小单: -1.1亿(-1.9%)    │    大单占比: 45.2%    中单: 32.1%    小单: 22.7%    │    北向资金: +0.85亿     融资余额: 25.6亿(-0.3%)     融券余额: 1.2亿(+2.1%)     资金净流入排名: 17/4832     活跃度: 中等     │    换手率排名: 456/4832    热度: ★★★☆☆",
                    id="money_flow_content_column"
                )
        


class MainLayoutTab(Container):
    """主界面标签页布局"""
    
    DEFAULT_CSS = """
    MainLayoutTab {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 5fr 5fr;
        grid-rows: 9fr 11fr;
        grid-gutter: 1;
        height: 1fr;
    }
    
    MainLayoutTab #stock_list_panel {
        column-span: 1;
        row-span: 1;
    }
    
    MainLayoutTab #user_group_panel {
        column-span: 1;
        row-span: 1;
    }
    
    MainLayoutTab #info_panel {
        column-span: 2;
        row-span: 1;
    }
    """
    BINDINGS = []
    
    def compose(self) -> ComposeResult:
        """组合主界面布局"""
        yield StockListPanel(id="stock_list_panel")
        yield UserGroupPanel(id="user_group_panel")
        # 下半区为智能终端控制台，替换原 InfoPanel（id 保持 info_panel 以复用布局与引用）。
        # 优雅降级：终端面板导入失败（如缺依赖）时退回信息面板，主界面仍可用。
        try:
            from .terminal.console_panel import TerminalConsolePanel
            yield TerminalConsolePanel(title="🖥 智能终端", id="info_panel")
        except Exception as exc:
            get_logger(__name__).error(f"终端面板不可用，退回信息面板: {exc}")
            from .widgets.line_panel import InfoPanel
            yield InfoPanel(title="系统信息（终端不可用）", id="info_panel")


class AnalysisLayoutTab(Container):
    """分析界面标签页布局"""
    
    def __init__(self, **kwargs):
        """初始化分析界面标签页"""
        super().__init__(**kwargs)
        self._app_ref = None
        self.analysis_panel = None
        self.logger = get_logger(__name__)
        
    def set_app_reference(self, app):
        """设置应用引用"""
        self._app_ref = app
        if self.analysis_panel:
            self.analysis_panel.set_app_reference(app)
    
    def on_key(self, event) -> None:
        """将键盘事件传递给AnalysisPanel"""
        #self.logger.debug(f"DEBUG: AnalysisLayoutTab 收到按键事件: {event.key}")
        if self.analysis_panel and hasattr(self.analysis_panel, 'on_key'):
            self.analysis_panel.on_key(event)
    
    DEFAULT_CSS = """
    AnalysisLayoutTab {
        layout: vertical;
        height: 1fr;
    }
    """
    
    def compose(self) -> ComposeResult:
        """组合分析界面布局"""
        self.analysis_panel = AnalysisPanel(id="analysis_panel")
        if self._app_ref:
            self.analysis_panel.set_app_reference(self._app_ref)
        yield self.analysis_panel


class StatusBar(Container):
    """状态栏组件"""
    
    DEFAULT_CSS = """
    StatusBar {
        height: 3;
        background: $surface;
        color: black;
        layout: horizontal;
        border: solid $accent;
        margin-bottom: 0;
    }
    
    StatusBar .status-item {
        width: 1fr;
        margin: 0 1;
        padding: 0 1;
        content-align: center middle;
        background: $accent;
        color: black;
    }
    
    StatusBar .connection-status {
        background: $success;
        color: black;
        padding: 0 1;
    }
    
    StatusBar .market-status {
        background: $warning;
        color: black;
        padding: 0 1;
    }
    
    StatusBar .refresh-mode {
        background: $primary;
        color: black;
        padding: 0 1;
    }
    """
    
    def compose(self) -> ComposeResult:
        """组合状态栏"""
        yield Static("🟢 已连接", classes="status-item connection-status", id="connection_status")
        yield Static("📈 开盘", classes="status-item market-status", id="market_status")
        yield Static("🔄 实时模式", classes="status-item refresh-mode", id="refresh_mode")
        yield Static("更新: 刚刚", classes="status-item", id="last_update")


class MonitorLayout(Container):
    """监控界面完整布局"""
    
    def __init__(self, **kwargs):
        """初始化监控界面布局"""
        super().__init__(**kwargs)
        self._app_ref = None
        self.logger = get_logger(__name__)
    
    BINDINGS = [
        Binding("q", "quit", "退出", priority=True),
        Binding("r", "refresh", "刷新", priority=True),
        Binding("h", "help", "帮助"),
        Binding("n", "add_stock", "添加股票"),
        Binding("k", "delete_stock", "删除股票"),
        Binding("t", "toggle_trading_mode", "切换交易模式"),
        Binding("escape", "go_back", "返回"),
        Binding("tab", "switch_tab", "切换标签"),
        # priority：DataTable 自带 enter=select_cursor 绑定，表格持焦（启动自动聚焦）
        # 时会先消费回车；须优先级绑定才能进入按 active_table 的分流。终端输入框
        # 场景由 _TERMINAL_GATED_ACTIONS + check_action 门控，不受影响。
        Binding("enter", "enter_analysis", "进入分析", priority=True),
        Binding("ctrl+c", "quit", "强制退出", priority=True),
        Binding("i", "open_ai_dialog", "AI问答", priority=True)
    ]
    
    DEFAULT_CSS = """
    MonitorLayout {
        layout: vertical;
    }
    
    MonitorLayout StatusBar {
        dock: top;
        height: 3;
    }
    
    MonitorLayout TabbedContent {
        height: 1fr;
        margin: 0;
    }
    
    MonitorLayout TabPane {
        padding: 0;
    }
    
    /* 全局样式 */
    .green { color: $success; }
    .red { color: $error; }
    .yellow { color: $warning; }
    .blue { color: $primary; }
    .cyan { color: $accent; }
    
    /* 表格样式 */
    DataTable > .datatable--header {
        background: $accent;
        color: $text;
    }
    
    DataTable > .datatable--cursor {
        background: $primary;
        color: $text;
    }
    
    /* 按钮样式 */
    Button.-success {
        background: $success;
        color: $text;
    }
    
    Button.-error {
        background: $error;
        color: $text;
    }
    
    Button.-primary {
        background: $primary;
        color: $text;
    }
    """
    
    # 终端 Input 持焦时应抑制的全局单键动作（避免打字触发退出/添加股票等）。
    _TERMINAL_GATED_ACTIONS = frozenset({
        "quit",
        "refresh",
        "help",
        "add_stock",
        "delete_stock",
        "toggle_trading_mode",
        "enter_analysis",
        "switch_tab",
        "open_ai_dialog",
    })

    def _is_terminal_input_focused(self) -> bool:
        """判断当前焦点是否在终端控制台的输入框。"""
        try:
            focused = self.app.focused
            return focused is not None and getattr(focused, "id", None) == "terminal_input"
        except Exception:
            return False

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """动态门控：终端输入框持焦时禁用受控单键动作。

        终端输入框获得焦点时，用户在打字（含 q/n/i 等单键），此时对全局单键动作
        返回 False 以禁用，使按键流入输入框；失焦时返回 True 正常启用。ctrl+c
        等强制退出不在门控集内，始终可用。

        Args:
            action: 动作名。
            parameters: 动作参数。

        Returns:
            ``False`` 禁用该动作；``True`` 正常启用。注意 Textual 的
            ``run_action`` 对 check_action 返回值做真值判断，返回 ``None``
            同样会拒绝分发（None 语义是"禁用但在 footer 显示"，不是"不干预"）。
        """
        if action in self._TERMINAL_GATED_ACTIONS and self._is_terminal_input_focused():
            return False
        return True

    async def action_delete_stock(self) -> None:
        """删除股票动作 - 委托给主应用处理"""
        if hasattr(self.app, 'action_delete_stock'):
            await self.app.action_delete_stock()
    async def action_add_stock(self) -> None:
        """添加股票动作 - 委托给主应用处理"""
        if hasattr(self.app, 'action_add_stock'):
            await self.app.action_add_stock()

    async def action_refresh(self) -> None:
        """刷新动作 - 委托给主应用处理"""
        if hasattr(self.app, 'action_refresh'):
            await self.app.action_refresh()

    async def action_help(self) -> None:
        """帮助动作 - 委托给主应用处理"""
        if hasattr(self.app, 'action_help'):
            await self.app.action_help()

    async def action_enter_analysis(self) -> None:
        """回车动作 - 按激活表格分流：持仓=买入(加仓)，股票=操作菜单，其余表格无回车行为"""
        app_core = getattr(self.app, 'app_core', None)
        active_table = getattr(app_core, 'active_table', None) if app_core is not None else None
        if active_table == "position":
            if hasattr(self.app, 'action_buy_selected'):
                await self.app.action_buy_selected()
            return
        if active_table == "stock":
            if hasattr(self.app, 'action_stock_menu'):
                await self.app.action_stock_menu()

    async def action_open_ai_dialog(self) -> None:
        """打开AI问答对话框 - 委托给主应用处理"""
        if hasattr(self.app, 'action_open_ai_dialog'):
            await self.app.action_open_ai_dialog()

    async def action_toggle_trading_mode(self) -> None:
        """切换交易模式 - 委托给主应用处理"""
        if hasattr(self.app, 'action_toggle_trading_mode'):
            await self.app.action_toggle_trading_mode()

    def compose(self) -> ComposeResult:
        """组合完整监控界面"""
        # 状态栏保留，但去除Header和Footer让界面更紧凑
        yield StatusBar(id="status_bar")

        # 主体标签页内容
        with TabbedContent(initial="main", id="main_tabs"):
            # 主界面标签页
            with TabPane("主界面", id="main"):
                yield MainLayoutTab(id="main_layout")


class ResponsiveLayout(Container):
    """响应式布局容器 - 支持不同终端尺寸"""
    
    # 响应式断点
    size_small = reactive(False)
    size_medium = reactive(False)
    size_large = reactive(True)
    
    DEFAULT_CSS = """
    ResponsiveLayout {
        layout: vertical;
    }
    
    /* 小屏幕布局 */
    ResponsiveLayout.-small MainLayoutTab {
        layout: vertical;
        grid-columns: 1fr;
    }
    
    ResponsiveLayout.-small StockListPanel {
        height: 60%;
    }
    
    ResponsiveLayout.-small UserGroupPanel {
        height: 25%;
    }
    
    ResponsiveLayout.-small InfoPanel {
        height: 15%;
    }
    
    /* 中等屏幕布局 */
    ResponsiveLayout.-medium MainLayoutTab {
        grid-columns: 6.5fr 3.5fr;
    }
    
    /* 大屏幕布局 (默认) */
    ResponsiveLayout.-large MainLayoutTab {
        grid-columns: 5fr 5fr;
    }
    """
    
    def watch_size(self) -> None:
        """监听窗口大小变化"""
        console_size = self.app.console.size
        width = console_size.width
        
        # 根据宽度设置响应式类
        if width < 80:
            self.set_class(True, "-small")
            self.set_class(False, "-medium", "-large")
            self.size_small = True
            self.size_medium = False
            self.size_large = False
        elif width < 120:
            self.set_class(True, "-medium")
            self.set_class(False, "-small", "-large")
            self.size_small = False
            self.size_medium = True
            self.size_large = False
        else:
            self.set_class(True, "-large")
            self.set_class(False, "-small", "-medium")
            self.size_small = False
            self.size_medium = False
            self.size_large = True
    
    def compose(self) -> ComposeResult:
        """组合响应式布局"""
        yield MonitorLayout(id="monitor_layout")


# 导出主要布局组件
__all__ = [
    "StockListPanel",
    "UserGroupPanel", 
    "AnalysisPanel",
    "MainLayoutTab",
    "StatusBar",
    "MonitorLayout",
    "ResponsiveLayout"
]