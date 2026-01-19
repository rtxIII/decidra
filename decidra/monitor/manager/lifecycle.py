"""
LifecycleManager - 应用生命周期管理模块

负责应用启动、退出、资源清理和任务监控
"""

import asyncio
import signal
import sys
import os
from typing import Optional, Dict, Any

from ...utils.global_vars import get_logger


class LifecycleManager:
    """
    生命周期管理器
    负责应用生命周期管理
    """
    
    def __init__(self, app_core, app_instance):
        """初始化生命周期管理器"""
        self.app_core = app_core
        self.app = app_instance
        self.logger = get_logger(__name__)
        
        # 任务监控
        self._task_monitor_timer: Optional[asyncio.Task] = None
        
        # 标签页状态管理器 - 延迟初始化
        self._tab_state_manager: Optional['TabStateManager'] = None
        
        self.logger.info("LifecycleManager 初始化完成")
    
    def _get_tab_state_manager(self):
        """获取标签页状态管理器（延迟初始化）"""
        if self._tab_state_manager is None:
            from .tab_state import TabStateManager
            self._tab_state_manager = TabStateManager(self.app_core)
        return self._tab_state_manager
    
    async def on_mount(self) -> None:
        """应用启动时的初始化"""
        self.logger.info("MonitorApp 正在启动...")
        
        # 加载配置
        await self.app_core.load_configuration()
        
        # 初始化数据管理器
        data_manager = getattr(self.app_core.app, 'data_manager', None)
        if data_manager:
            await data_manager.initialize_data_managers()
        
        # 获取新UI组件的引用
        ui_manager = getattr(self.app_core.app, 'ui_manager', None)
        if ui_manager:
            await ui_manager.setup_ui_references()
        
        # 加载默认股票列表
        if ui_manager:
            await ui_manager.load_default_stocks()
        
        # 加载用户分组数据
        group_manager = getattr(self.app_core.app, 'group_manager', None)
        if group_manager:
            await group_manager.load_user_groups()
        
        # 启动数据刷新
        if data_manager:
            await data_manager.start_data_refresh()
        
        # 初始化info
        if ui_manager:
            await ui_manager.initialize_info()
        
        # 初始化AnalysisPanel InfoPanel
        await self.initialize_analysis_info_panel()
        
        # 启动任务监控
        await self.start_task_monitoring()
        
        # 恢复标签页状态（在所有初始化完成后）临时关闭
        #await self.restore_tab_state()
        
        self.logger.info("MonitorApp 启动完成")
        # 向信息面板显示启动完成信息
        if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
            await self.app_core.app.ui_manager.info_panel.log_info("应用程序启动完成", "系统")
        
        # 向AnalysisPanel InfoPanel显示启动完成信息（如果存在的话）
        await self.log_to_analysis_info_panel("分析模块启动完成，可以开始股票分析", "系统")
        
        # 更新状态显示
        await self.app_core.update_status_display()
    
    async def start_task_monitoring(self) -> None:
        """启动任务监控"""
        if self._task_monitor_timer and not self._task_monitor_timer.done():
            return
            
        self._task_monitor_timer = asyncio.create_task(self.task_monitor_loop())
        self.logger.info("任务监控已启动")
    
    async def task_monitor_loop(self) -> None:
        """任务监控循环"""
        while not self.app_core._is_quitting:
            try:
                await self.log_task_queue_status()
                await asyncio.sleep(30)  # 每30秒记录一次任务状态
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"任务监控循环错误: {e}")
                await asyncio.sleep(30)
    
    async def log_task_queue_status(self) -> None:
        """记录当前任务队列状态"""
        try:
            loop = asyncio.get_event_loop()
            all_tasks = asyncio.all_tasks(loop)
            
            # 统计不同类型的任务
            pending_tasks = [task for task in all_tasks if not task.done()]
            running_tasks = [task for task in all_tasks if not task.done() and not task.cancelled()]
            
            # 获取任务名称和详细信息，过滤UI相关任务
            task_info = []
            ui_tasks_count = 0
            app_tasks_count = 0
            
            # UI相关任务的关键词
            ui_keywords = [
                'message pump', 'animator', 'label', 'static', 'footer', 'tab',
                'button', 'input', 'datatable', 'container', 'widget', 'textual'
            ]
            
            for task in pending_tasks:
                task_name = "Unknown"
                if hasattr(task, 'get_name'):
                    task_name = task.get_name()
                elif hasattr(task, '_coro'):
                    coro_name = getattr(task._coro, '__name__', None)
                    if coro_name:
                        task_name = coro_name
                    else:
                        task_name = str(task._coro)[:50]
                
                task_status = "PENDING"
                if task.cancelled():
                    task_status = "CANCELLED"
                elif task.done():
                    task_status = "DONE"
                
                # 判断是否为UI任务
                is_ui_task = any(keyword in task_name.lower() for keyword in ui_keywords)
                
                if is_ui_task:
                    ui_tasks_count += 1
                else:
                    app_tasks_count += 1
                    task_info.append(f"{task_name}({task_status})")
            
            # 记录详细的任务信息
            #self.logger.info(f"任务队列状态:")
            #self.logger.info(f"  总任务数: {len(all_tasks)}")
            #self.logger.info(f"  待处理任务: {len(pending_tasks)} (UI任务: {ui_tasks_count}, 应用任务: {app_tasks_count})")
            #self.logger.info(f"  运行中任务: {len(running_tasks)}")
            
            # 只显示应用相关任务
            if app_tasks_count > 0:
                self.logger.info(f"  应用任务详情: {', '.join(task_info[:10])}")  # 只显示前10个
                if app_tasks_count > 10:
                    self.logger.info(f"  ... 还有 {app_tasks_count - 10} 个应用任务")
            else:
                self.logger.info(f"  无应用相关待处理任务")
            
            # 如果应用任务数量过多，发出警告
            if app_tasks_count > 100:
                self.logger.warning(f"检测到大量应用任务({app_tasks_count})，可能存在任务积累问题")
            elif len(pending_tasks) > 500:  # UI任务过多也要警告
                self.logger.warning(f"检测到大量UI任务({ui_tasks_count})，可能存在界面更新问题")
                
        except Exception as e:
            self.logger.error(f"记录任务队列状态失败: {e}")
    
    async def action_quit(self) -> None:
        """退出应用动作"""
        self.logger.info("应用程序正在退出...")
        # 向信息面板显示退出信息
        if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
            await self.app_core.app.ui_manager.info_panel.log_info("应用程序正在退出", "系统")
        
        # 向AnalysisPanel InfoPanel显示退出信息
        await self.log_to_analysis_info_panel("分析模块正在关闭...", "系统")
        
        # 保存标签页状态
        await self.save_tab_state()
        
        # 设置优雅退出标志
        self.app_core._is_quitting = True
        
        try:
            # 1. 立即停止所有定时器和循环任务
            data_manager = getattr(self.app_core.app, 'data_manager', None)
            if data_manager and data_manager.refresh_timer:
                data_manager.refresh_timer.cancel()
                data_manager.refresh_timer = None
                self.logger.debug("刷新定时器已停止")
            
            if self._task_monitor_timer:
                self._task_monitor_timer.cancel()
                self._task_monitor_timer = None
                self.logger.debug("任务监控定时器已停止")
            
            # 2. 取消所有异步任务
            try:
                # 记录退出前的任务状态
                await self.log_task_queue_status()
                
                # 获取当前事件循环中的所有任务
                loop = asyncio.get_event_loop()
                pending_tasks = [task for task in asyncio.all_tasks(loop) 
                               if not task.done() and task != asyncio.current_task()]
                
                if pending_tasks:
                    self.logger.info(f"取消 {len(pending_tasks)} 个待处理任务")
                    # 取消所有待处理任务
                    for task in pending_tasks:
                        if not task.cancelled():
                            task.cancel()
                    
                    # 等待任务取消完成
                    await asyncio.wait_for(
                        asyncio.gather(*pending_tasks, return_exceptions=True),
                        timeout=2.0
                    )
                    self.logger.debug("异步任务取消完成")
                else:
                    self.logger.debug("没有待处理任务需要取消")
            except asyncio.TimeoutError:
                self.logger.warning("部分异步任务取消超时")
            except Exception as e:
                self.logger.warning(f"取消异步任务时出错: {e}")
            
            # 3. 清理数据流管理器
            try:
                if data_manager and hasattr(data_manager, 'cleanup'):
                    await asyncio.wait_for(
                        data_manager.cleanup(),
                        timeout=1.5
                    )
                    self.logger.info("数据流管理器清理完成")
            except asyncio.TimeoutError:
                self.logger.warning("数据流管理器清理超时")
            except Exception as e:
                self.logger.warning(f"数据流管理器清理失败: {e}")
            
            # 4. 关闭富途连接
            try:
                if data_manager and hasattr(data_manager.futu_market, 'client') and data_manager.futu_market.client:
                    # 在线程池中执行同步的关闭操作
                    loop = asyncio.get_event_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, data_manager.futu_market.client.disconnect),
                        timeout=1.5
                    )
                    self.logger.info("富途市场连接关闭完成")
            except asyncio.TimeoutError:
                self.logger.warning("富途市场连接关闭超时")
            except Exception as e:
                self.logger.warning(f"富途市场连接关闭失败: {e}")

            # 5. 关闭富途交易连接
            try:
                futu_trade = getattr(self.app_core.app, 'futu_trade', None)
                if futu_trade and hasattr(futu_trade, 'client') and futu_trade.client:
                    # 在线程池中执行同步的关闭操作
                    loop = asyncio.get_event_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, futu_trade.client.disconnect),
                        timeout=1.5
                    )
                    self.logger.info("富途交易连接关闭完成")
            except asyncio.TimeoutError:
                self.logger.warning("富途交易连接关闭超时")
            except Exception as e:
                self.logger.warning(f"富途交易连接关闭失败: {e}")
            
            # 5. 保存配置（最低优先级）
            try:
                await self.app_core.save_config_async()
                self.logger.info("配置保存完成")
            except Exception as e:
                self.logger.warning(f"配置保存失败: {e}")
            
        except Exception as e:
            self.logger.error(f"退出过程中发生错误: {e}")
        finally:
            # 6. 优雅地退出应用
            self.logger.info("准备退出应用")
            try:
                # 使用 Textual 的标准退出方法
                self.app.exit(return_code=0)
            except Exception as e:
                self.logger.error(f"应用退出失败: {e}")
                # 如果标准退出失败，尝试其他方式
                try:
                    # 设置退出标志让主循环自然结束
                    if hasattr(self.app, '_exit_flag'):
                        self.app._exit_flag = True
                    # 发送退出信号
                    os.kill(os.getpid(), signal.SIGTERM)
                except:
                    # 最后的手段：使用 sys.exit() 而不是 os._exit()
                    self.logger.warning("使用 sys.exit() 退出")
                    sys.exit(0)
    
    async def cleanup_resources(self) -> None:
        """清理资源"""
        try:
            cleanup_tasks = []
            
            # 断开富途连接
            data_manager = getattr(self.app_core.app, 'data_manager', None)
            if data_manager and data_manager.futu_market:
                loop = asyncio.get_event_loop()
                cleanup_task = loop.run_in_executor(None, data_manager.cleanup_futu_market)
                cleanup_tasks.append(cleanup_task)
            analysis_data_manager = getattr(self.app_core.app, 'analysis_data_manager', None)
            if analysis_data_manager and analysis_data_manager.futu_market:
                loop = asyncio.get_event_loop()
                cleanup_task = loop.run_in_executor(None, analysis_data_manager.cleanup_futu_market)
                cleanup_tasks.append(cleanup_task)

            # 停止数据流管理器
            if data_manager and hasattr(data_manager, 'cleanup'):
                cleanup_tasks.append(data_manager.cleanup())
            
            # 并发执行清理任务，但设置总超时
            if cleanup_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*cleanup_tasks, return_exceptions=True),
                        timeout=3.0
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("部分清理任务超时")
            
            self.logger.info("资源清理完成")
            
        except Exception as e:
            self.logger.error(f"资源清理失败: {e}")
            # 继续退出过程，不让异常阻止程序退出
    
    async def initialize_analysis_info_panel(self) -> None:
        """初始化AnalysisPanel中的InfoPanel"""
        try:
            # 查找AnalysisPanel中的InfoPanel
            analysis_info_panel = self.get_analysis_info_panel()
            if analysis_info_panel:
                await analysis_info_panel.log_info("分析面板已初始化", "系统")
                self.logger.info("AnalysisPanel InfoPanel 初始化完成")
            else:
                self.logger.debug("未找到AnalysisPanel InfoPanel，可能面板尚未创建")
        except Exception as e:
            self.logger.warning(f"初始化AnalysisPanel InfoPanel失败: {e}")
    
    def get_analysis_info_panel(self):
        """获取AnalysisPanel中的InfoPanel实例"""
        try:
            self.logger.debug("开始查找AnalysisPanel InfoPanel...")
            
            # 尝试查找ai_info_panel
            analysis_panels = self.app.query("AnalysisPanel")
            self.logger.debug(f"找到 {len(analysis_panels)} 个 AnalysisPanel")
            
            if analysis_panels:
                for i, panel in enumerate(analysis_panels):
                    try:
                        self.logger.debug(f"检查 AnalysisPanel #{i}")
                        info_panel = panel.query_one("#ai_info_panel")
                        if info_panel:
                            self.logger.debug(f"在 AnalysisPanel #{i} 中找到 InfoPanel: {info_panel}")
                            return info_panel
                    except Exception as panel_error:
                        self.logger.debug(f"AnalysisPanel #{i} 中未找到 InfoPanel: {panel_error}")
                        continue
            
            # 备用方案：直接查找ai_info_panel
            try:
                self.logger.debug("尝试直接查找 #ai_info_panel")
                info_panel = self.app.query_one("#ai_info_panel")
                self.logger.debug(f"直接找到 InfoPanel: {info_panel}")
                return info_panel
            except Exception as direct_error:
                self.logger.debug(f"直接查找 InfoPanel 失败: {direct_error}")
                return None
                
        except Exception as e:
            self.logger.debug(f"获取AnalysisPanel InfoPanel失败: {e}")
            return None
    
    async def log_to_analysis_info_panel(self, message: str, category: str = "分析", level: str = "INFO") -> None:
        """向AnalysisPanel的InfoPanel记录信息"""
        try:
            analysis_info_panel = self.get_analysis_info_panel()
            if analysis_info_panel:
                if level.upper() == "ERROR":
                    await analysis_info_panel.log_error(message, category)
                elif level.upper() == "WARNING":
                    await analysis_info_panel.log_warning(message, category)
                else:
                    await analysis_info_panel.log_info(message, category)
            else:
                # 如果没有找到AnalysisPanel InfoPanel，记录到日志
                self.logger.info(f"[{category}] {message}")
        except Exception as e:
            self.logger.error(f"向AnalysisPanel InfoPanel记录信息失败: {e}")
    
    async def log_analysis_data(self, stock_code: str, data_type: str, status: str, details: str = "") -> None:
        """记录分析数据相关信息"""
        message = f"{stock_code} {data_type} {status}"
        if details:
            message += f" - {details}"
        await self.log_to_analysis_info_panel(message, "数据")
    
    async def log_analysis_event(self, event_type: str, description: str, level: str = "INFO") -> None:
        """记录分析事件信息"""
        await self.log_to_analysis_info_panel(f"{event_type}: {description}", "事件", level)
    
    async def log_ai_analysis_result(self, analysis_type: str, result_summary: str) -> None:
        """记录AI分析结果"""
        await self.log_to_analysis_info_panel(f"{analysis_type} 完成 - {result_summary}", "AI分析")
    
    async def on_analysis_panel_created(self) -> None:
        """当AnalysisPanel被创建时调用，显示欢迎信息"""
        try:
            # 等待一小段时间确保InfoPanel完全初始化
            await asyncio.sleep(0.1)
            
            # 检查是否能找到InfoPanel
            analysis_info_panel = self.get_analysis_info_panel()
            if analysis_info_panel:
                await analysis_info_panel.log_info("欢迎使用股票分析功能！", "系统")
                await analysis_info_panel.log_info("您可以选择股票进行深度分析", "系统")
                self.logger.info("AnalysisPanel 欢迎信息已显示")
            else:
                self.logger.debug("AnalysisPanel创建后仍无法找到InfoPanel")
        except Exception as e:
            self.logger.warning(f"显示AnalysisPanel欢迎信息失败: {e}")
    
    def setup_analysis_panel_welcome(self) -> None:
        """设置分析面板的欢迎信息（供UI管理器调用）"""
        self.logger.info("收到AnalysisPanel创建通知，开始设置欢迎信息")
        # 创建一个异步任务来处理欢迎信息
        asyncio.create_task(self.on_analysis_panel_created())
    
    # ================== 标签页状态管理方法 ==================
    
    async def save_tab_state(self) -> bool:
        """保存当前标签页状态"""
        try:
            tab_manager = self._get_tab_state_manager()
            success = await tab_manager.save_tab_state()
            
            if success:
                self.logger.info("分析标签页状态保存成功")
                await self.log_to_analysis_info_panel("分析标签页状态已保存", "系统")
            else:
                self.logger.warning("分析标签页状态保存失败")
            
            return success
            
        except Exception as e:
            self.logger.error(f"保存标签页状态失败: {e}")
            return False
    
    async def restore_tab_state(self) -> bool:
        """恢复标签页状态"""
        try:
            tab_manager = self._get_tab_state_manager()
            success = await tab_manager.restore_tab_state()
            
            if success:
                self.logger.info("标签页状态恢复成功")
            else:
                self.logger.info("没有需要恢复的标签页状态")
            
            return success
            
        except Exception as e:
            self.logger.error(f"恢复标签页状态失败: {e}")
            return False
    
    async def clear_saved_tab_state(self) -> bool:
        """清除保存的标签页状态"""
        try:
            tab_manager = self._get_tab_state_manager()
            success = await tab_manager.clear_saved_state()
            
            if success:
                self.logger.info("标签页状态已清除")
                await self.log_to_analysis_info_panel("已清除保存的标签页状态", "系统")
            
            return success
            
        except Exception as e:
            self.logger.error(f"清除标签页状态失败: {e}")
            return False
    
    def get_tab_state_info(self) -> Dict[str, Any]:
        """获取标签页状态信息"""
        try:
            tab_manager = self._get_tab_state_manager()
            return tab_manager.get_state_info()
            
        except Exception as e:
            self.logger.error(f"获取标签页状态信息失败: {e}")
            return {"has_saved_state": False, "error": str(e)}
    