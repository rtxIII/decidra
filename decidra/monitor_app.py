#!/usr/bin/env python3
"""
Decidra股票监控应用程序 - 重构版本
基于Textual框架的终端用户界面实现

使用组合模式将原有的MonitorApp类拆分为多个功能明确的管理器模块
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any

from textual.events import Key
from textual.app import App, ComposeResult
from textual.widgets import DataTable, TabbedContent, TabPane
from textual.binding import Binding
from textual.screen import Screen

# 项目内部导入
from .modules.futu_market import FutuMarket
from .modules.futu_trade import FutuTrade
from .utils.global_vars import get_logger

# 导入新的UI布局组件
from .monitor.monitor_layout import MonitorLayout
from .monitor.widgets.splash_screen import SplashScreen

# 导入重构后的管理器模块
from .monitor.app_core import AppCore
from .monitor.main import (
    DataManager, 
    EventHandler
)
from .monitor.manager import (
    UIManager, UserDataManager, LifecycleManager, TabStateManager
)

# 导入分析页面组件
from .monitor.analysis import (
    AnalysisDataManager,
    ChartManager,
    AIAnalysisManager
)


class SplashScreenView(Screen):
    """启动页面屏幕"""
    
    def compose(self) -> ComposeResult:
        yield SplashScreen(auto_jump_delay=1)


class MonitorScreen(Screen):
    """主监控界面屏幕"""
    
    def compose(self) -> ComposeResult:
        yield MonitorLayout(id="monitor_layout")


class MonitorApp(App):
    """
    Decidra股票监控主应用程序 - 重构版本
    基于Textual框架实现终端界面，使用组合模式集成各功能管理器
    """
    
    # 键盘绑定定义 - 必须在类级别定义
    BINDINGS = [
        Binding("q", "quit", "退出", priority=True),
        Binding("h", "help", "帮助"),
        Binding("n", "add_stock", "添加股票"),
        Binding("k", "delete_stock", "删除股票"),
        Binding("t", "toggle_trading_mode", "切换交易模式"),
        Binding("o", "place_order", "新订单"),
        Binding("b", "buy_selected", "买入"),
        Binding("r", "refresh", "刷新数据"),
        Binding("escape", "go_back", "返回"),
        Binding("tab", "switch_tab", "切换标签"),
        Binding("w", "cursor_up", "向上移动"),
        Binding("s", "cursor_down", "向下移动"),
        Binding("a", "focus_left_table", "焦点左移"),
        Binding("d", "focus_right_table", "焦点右移"),
        Binding("space", "select_group", "选择分组"),
        Binding("x", "global_switch_tab_left", "上一个标签", priority=True),
        Binding("c", "global_switch_tab_right", "下一个标签", priority=True),
        Binding("ctrl+c", "quit", "强制退出", priority=True),
        Binding("space+w", "close_current_tab", "关闭标签页", priority=True),
        Binding("ctrl+w", "close_current_tab", "关闭标签页", priority=True),
        Binding("i", "open_ai_dialog", "AI问答", priority=True),
    ]
    
    def __init__(self):
        """初始化监控应用"""
        super().__init__()
        
        # 设置主题
        self.theme = "tokyo-night"
        
        # 设置日志
        self.logger = get_logger(__name__)
        
        # 启动页面相关状态
        self.show_splash = True
        self.managers_initialized = False
        
        self.logger.info("MonitorApp 初始化完成")
    
    def _initialize_managers(self):
        """延迟初始化管理器（在启动页面完成后）"""
        if self.managers_initialized:
            return
            
        # 创建共享的富途市场实例
        self.futu_market = FutuMarket()
        # 标记为共享实例，防止其他组件重复关闭
        self.futu_market._is_shared_instance = True

        # 创建共享的富途交易实例
        self.futu_trade = FutuTrade()
        # 标记为共享实例，防止其他组件重复关闭
        self.futu_trade._is_shared_instance = True
        
        # 初始化应用核心
        self.app_core = AppCore(self)

        # 初始化各个管理器
        self.data_manager = DataManager(self.app_core, self.futu_market, self.futu_trade)
        self.ui_manager = UIManager(self.app_core, self)
        self.group_manager = UserDataManager(self.app_core, self.futu_market)
        self.event_handler = EventHandler(self.app_core, self)
        self.lifecycle_manager = LifecycleManager(self.app_core, self)
        
        # 初始化分析页面管理器
        self.analysis_data_manager = AnalysisDataManager(self.app_core, self.futu_market)
        self.chart_manager = ChartManager(self.analysis_data_manager)
        self.ai_analysis_manager = AIAnalysisManager(self.analysis_data_manager)
        
        # 将管理器引用添加到app_core，以便各管理器之间可以相互访问
        self.app_core.data_manager = self.data_manager
        self.app_core.ui_manager = self.ui_manager
        self.app_core.group_manager = self.group_manager
        self.app_core.event_handler = self.event_handler
        self.app_core.lifecycle_manager = self.lifecycle_manager
        
        # 将分析管理器引用添加到app_core
        self.app_core.analysis_data_manager = self.analysis_data_manager
        self.app_core.chart_manager = self.chart_manager
        self.app_core.ai_analysis_manager = self.ai_analysis_manager
        
        self.managers_initialized = True
        self.logger.info("管理器初始化完成")
    
    def compose(self) -> ComposeResult:
        """构建用户界面"""
        # 初始时显示启动页面
        if self.show_splash:
            yield SplashScreen(auto_jump_delay=1)
        else:
            yield MonitorLayout(id="monitor_layout")
    
    def on_key(self, event: Key) -> None:
        """处理按键事件"""
        if self.show_splash:
            # 启动页面阶段的按键处理
            pass
        else:
            # 主界面阶段的按键处理 - 委托给事件处理器
            self.event_handler.on_key(event)
    
    async def on_mount(self) -> None:
        """应用启动时的初始化"""
        if self.show_splash:
            self.logger.info("显示启动页面")
        else:
            # 主界面初始化 - 委托给生命周期管理器
            await self.lifecycle_manager.on_mount()
    
    async def on_splash_screen_status_complete(self, message) -> None:
        """处理启动页面系统状态检查完成"""
        self.logger.info("启动页面系统检查完成")
    
    async def on_splash_screen_auto_jump_requested(self, message) -> None:
        """处理启动页面自动跳转请求"""
        self.logger.info("收到自动跳转请求，切换到主界面")
        await self._switch_to_main_interface()
    
    async def on_splash_screen_action_selected(self, message) -> None:
        """处理启动页面用户操作选择"""
        action = message.action
        self.logger.info(f"用户选择操作: {action}")
        
        if action == "config":
            # 显示配置帮助或跳转到配置
            self.logger.info("用户选择配置管理")
        elif action == "help":
            # 显示帮助信息
            self.logger.info("用户选择帮助")
    
    async def _switch_to_main_interface(self) -> None:
        """切换到主界面"""
        try:
            self.logger.info("开始切换到主界面")
        
            
            # 初始化管理器
            self._initialize_managers()
            
            # 切换状态
            self.show_splash = False
            
            # 重新构建界面
            await self.recompose()
            
            # UI组件应用引用现在通过动态创建分析界面时设置
            
            # 初始化主界面
            await self.lifecycle_manager.on_mount()
            
            self.logger.info("成功切换到主界面")
            
        except Exception as e:
            self.logger.error(f"切换到主界面失败: {e}")
            # 如果切换失败，可以选择显示错误信息或退出
    
    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """处理表格行选择事件 - 委托给事件处理器"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.on_data_table_row_selected(event)
    
    # 动作方法 - 委托给事件处理器
    async def action_add_stock(self) -> None:
        """添加股票动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_add_stock()
    
    async def action_delete_stock(self) -> None:
        """删除股票动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_delete_stock()
    
    async def action_refresh(self) -> None:
        """手动刷新动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_refresh()
    
    async def action_help(self) -> None:
        """显示帮助动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_help()
    
    async def action_go_back(self) -> None:
        """返回主界面动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_go_back()
    
    async def action_switch_tab(self) -> None:
        """切换标签页动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_switch_tab()
    
    async def action_cursor_up(self) -> None:
        """光标向上移动"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_cursor_up()
    
    async def action_cursor_down(self) -> None:
        """光标向下移动"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_cursor_down()
    
    async def action_select_group(self) -> None:
        """选择当前光标所在的分组"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_select_group()

    async def action_place_order(self) -> None:
        """新订单动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_place_order()

    async def action_buy_selected(self) -> None:
        """买入选中标的动作（b键 / 持仓表回车加仓）"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_buy_selected()

    async def action_focus_left_table(self) -> None:
        """左移焦点到股票表格"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_focus_left_table()
    
    async def action_focus_right_table(self) -> None:
        """右移焦点到分组表格"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_focus_right_table()
    
    async def action_global_switch_tab_left(self) -> None:
        """全局向左切换标签页（x键）"""
        if not self.show_splash and self.managers_initialized:
            try:
                # 获取主标签页容器
                main_tabs = self.query_one("#main_tabs", TabbedContent)
                
                # 获取主界面标签页（过滤掉子标签页）
                all_panes = list(main_tabs.query(TabPane))
                main_level_tabs = []
                for pane in all_panes:
                    if pane.id == 'main' or pane.id.startswith('analysis_'):
                        main_level_tabs.append(pane.id)
                
                all_tabs = list(dict.fromkeys(main_level_tabs))  # 去重
                self.logger.debug(f"DEBUG: MonitorApp x键 - 全局标签页: {all_tabs}")
                
                if len(all_tabs) <= 1:
                    self.logger.debug("DEBUG: MonitorApp 标签页数量不足，无法切换")
                    return
                    
                current_active = main_tabs.active
                try:
                    current_index = all_tabs.index(current_active)
                except ValueError:
                    current_index = 0
                
                prev_index = (current_index - 1) % len(all_tabs)
                target_tab = all_tabs[prev_index]
                main_tabs.active = target_tab
                self.logger.debug(f"DEBUG: MonitorApp 全局向左切换 {current_active} -> {target_tab}")
                
            except Exception as e:
                self.logger.debug(f"DEBUG: MonitorApp 全局向左切换失败: {e}")
    
    async def action_global_switch_tab_right(self) -> None:
        """全局向右切换标签页（c键）"""
        if not self.show_splash and self.managers_initialized:
            try:
                # 获取主标签页容器
                main_tabs = self.query_one("#main_tabs", TabbedContent)
                
                # 获取主界面标签页（过滤掉子标签页）
                all_panes = list(main_tabs.query(TabPane))
                main_level_tabs = []
                for pane in all_panes:
                    if pane.id == 'main' or pane.id.startswith('analysis_'):
                        main_level_tabs.append(pane.id)
                
                all_tabs = list(dict.fromkeys(main_level_tabs))  # 去重
                self.logger.debug(f"DEBUG: MonitorApp c键 - 全局标签页: {all_tabs}")
                
                if len(all_tabs) <= 1:
                    self.logger.debug("DEBUG: MonitorApp 标签页数量不足，无法切换")
                    return
                    
                current_active = main_tabs.active
                try:
                    current_index = all_tabs.index(current_active)
                except ValueError:
                    current_index = 0
                
                next_index = (current_index + 1) % len(all_tabs)
                target_tab = all_tabs[next_index]
                main_tabs.active = target_tab
                self.logger.debug(f"DEBUG: MonitorApp 全局向右切换 {current_active} -> {target_tab}")
                
            except Exception as e:
                self.logger.debug(f"DEBUG: MonitorApp 全局向右切换失败: {e}")
    
    async def action_close_current_tab(self) -> None:
        """关闭当前标签页动作（Cmd+W / Ctrl+W）"""
        if not self.show_splash and self.managers_initialized:
            try:
                ui_manager = getattr(self, 'ui_manager', None)
                if ui_manager:
                    success = await ui_manager.close_current_tab()
                    if success:
                        self.logger.info("成功关闭当前标签页")
                    else:
                        self.logger.debug("当前标签页不能关闭或关闭失败")
                else:
                    self.logger.error("UIManager未初始化，无法关闭标签页")
            except Exception as e:
                self.logger.error(f"关闭当前标签页失败: {e}")
    
    async def action_open_ai_dialog(self) -> None:
        """打开AI快捷问答对话框"""
        if not self.show_splash and self.managers_initialized:
            # 使用 run_worker 调用info_panel的AI对话框方法，避免 push_screen_wait 错误
            ui_manager = getattr(self, 'ui_manager', None)
            if ui_manager and ui_manager.info_panel:
                ui_manager.info_panel.run_worker(
                    ui_manager.info_panel._show_ai_dialog(),
                    exclusive=True,
                    group="ai_dialog"
                )
            else:
                self.logger.error("UIManager或InfoPanel未初始化，无法打开AI对话框")

    async def action_toggle_trading_mode(self) -> None:
        """切换交易模式动作"""
        if not self.show_splash and self.managers_initialized:
            await self.event_handler.action_toggle_trading_mode()

    async def action_quit(self) -> None:
        """退出应用动作"""
        if self.managers_initialized:
            await self.lifecycle_manager.action_quit()
        else:
            await super().action_quit()

    # 便捷访问属性，保持向后兼容性
    @property
    def current_stock_code(self) -> Optional[str]:
        """当前选中的股票代码"""
        if self.managers_initialized:
            return self.app_core.current_stock_code
        return None
    
    @current_stock_code.setter
    def current_stock_code(self, value: Optional[str]):
        """设置当前选中的股票代码"""
        if self.managers_initialized:
            self.app_core.current_stock_code = value
    
    @property
    def connection_status(self):
        """连接状态"""
        if self.managers_initialized:
            return self.app_core.connection_status
        return "未初始化"
    
    @connection_status.setter
    def connection_status(self, value):
        """设置连接状态"""
        if self.managers_initialized:
            self.app_core.connection_status = value
    
    @property
    def market_status(self):
        """市场状态"""
        if self.managers_initialized:
            return self.app_core.market_status
        return "未知"
    
    @market_status.setter
    def market_status(self, value):
        """设置市场状态"""
        if self.managers_initialized:
            self.app_core.market_status = value
    
    @property
    def monitored_stocks(self) -> List[str]:
        """监控股票列表"""
        if self.managers_initialized:
            return self.app_core.monitored_stocks
        return []
    
    @monitored_stocks.setter
    def monitored_stocks(self, value: List[str]):
        """设置监控股票列表"""
        if self.managers_initialized:
            self.app_core.monitored_stocks = value
    
    @property
    def stock_data(self) -> Dict[str, Any]:
        """股票数据"""
        if self.managers_initialized:
            return self.app_core.stock_data
        return {}
    
    # 为了保持兼容性而保留的引用属性
    @property
    def stock_table(self) -> Optional[DataTable]:
        """股票表格引用"""
        return self.ui_manager.stock_table if self.ui_manager else None
    
    @property
    def group_table(self) -> Optional[DataTable]:
        """分组表格引用"""
        return self.ui_manager.group_table if self.ui_manager else None
    
    @property
    def info_panel(self):
        """信息面板引用"""
        return self.ui_manager.info_panel if self.ui_manager else None

    # 分析页面管理器便捷访问属性
    @property
    def analysis_data(self):
        """分析数据管理器引用"""
        return self.analysis_data_manager
    
    @property
    def chart(self):
        """图表管理器引用"""
        return self.chart_manager
    
    @property
    def ai_analysis(self):
        """AI分析管理器引用"""
        return self.ai_analysis_manager
    


def main():
    """主函数"""
    app = MonitorApp()
    app.run()


if __name__ == "__main__":
    main()