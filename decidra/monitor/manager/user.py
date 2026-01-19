"""
UserDataManager - 用户数据管理模块

负责用户分组数据加载、分组操作和分组与股票列表的关联管理
"""

import asyncio
from typing import List, Dict, Optional, Any

from ...modules.futu_market import FutuMarket
from ...utils.global_vars import get_logger


class UserDataManager:
    """
    分组管理器
    负责用户分组管理
    """
    
    def __init__(self, app_core, futu_market: FutuMarket):
        """初始化分组管理器"""
        self.app_core = app_core
        self.futu_market = futu_market
        self.logger = get_logger(__name__)
        
        self.logger.info("UserDataManager 初始化完成")
    
    async def load_user_groups(self) -> None:
        """加载用户分组数据"""
        # 引用UI管理器，避免循环导入
        ui_manager = getattr(self.app_core.app, 'ui_manager', None)
        if not ui_manager or not ui_manager.group_table:
            self.logger.warning("group_table 未初始化，跳过加载用户分组")
            return
            
        try:
            # 在线程池中执行同步的富途API调用
            loop = asyncio.get_event_loop()
            user_groups = await loop.run_in_executor(
                None, 
                self.futu_market.get_user_security_group,
                "CUSTOM"  # 获取所有分组
            )
            
            # 清空现有数据
            ui_manager.group_table.clear()
            self.app_core.group_data.clear()
            
            # 添加分组数据到表格
            processed_groups = []
            if user_groups is not None:
                import pandas as pd
                if isinstance(user_groups, pd.DataFrame):
                    if not user_groups.empty:
                        processed_groups = user_groups.to_dict('records')
                elif isinstance(user_groups, dict):
                    processed_groups = [user_groups]
                elif isinstance(user_groups, list):
                    processed_groups = user_groups
                    
            if processed_groups:
                self.logger.info(f"获取到 {len(processed_groups)} 个分组数据")
                
                loop = asyncio.get_event_loop()
                
                for i, group in enumerate(processed_groups):
                    try:
                        if isinstance(group, dict):
                            # 富途API返回的字典格式
                            group_name = group.get('group_name', f'分组{i+1}')
                            group_type = group.get('group_type', 'CUSTOM')
                            
                            # 单独获取分组中的股票列表
                            try:
                                group_stocks_result = await loop.run_in_executor(
                                    None,
                                    self.futu_market.get_user_security,
                                    group_name
                                )
                                
                                # 处理返回的DataFrame
                                stock_list = []
                                if group_stocks_result is not None:
                                    import pandas as pd
                                    if isinstance(group_stocks_result, pd.DataFrame) and not group_stocks_result.empty:
                                        stock_list = group_stocks_result.to_dict('records')
                                    elif isinstance(group_stocks_result, list):
                                        stock_list = group_stocks_result
                                    elif isinstance(group_stocks_result, dict):
                                        stock_list = [group_stocks_result]
                                
                                stock_count = len(stock_list)
                                #self.logger.debug(f"获取分组 '{group_name}' 的股票: {stock_count} 只")
                            except Exception as e:
                                self.logger.warning(f"获取分组 '{group_name}' 股票失败: {e}")
                                stock_list = []
                                stock_count = 0
                            
                            # 存储分组数据
                            group_data = {
                                'name': group_name,
                                'stock_list': stock_list,
                                'stock_count': stock_count,
                                'type': group_type
                            }
                            self.app_core.group_data.append(group_data)
                            
                            # 添加分组行
                            ui_manager.group_table.add_row(
                                group_name,
                                str(stock_count),
                                group_type
                            )
                            self.logger.debug(f"添加分组: {group_name}, 股票数: {stock_count}")
                            
                        elif isinstance(group, (list, tuple)) and len(group) >= 2:
                            # 可能的元组格式 (group_name, stock_list)
                            group_name = str(group[0])
                            stock_count = len(group[1]) if isinstance(group[1], (list, tuple)) else 0
                            
                            group_data = {
                                'name': group_name,
                                'stock_list': group[1] if isinstance(group[1], (list, tuple)) else [],
                                'stock_count': stock_count,
                                'type': 'CUSTOM'
                            }
                            self.app_core.group_data.append(group_data)
                            
                            ui_manager.group_table.add_row(
                                group_name,
                                str(stock_count),
                                "CUSTOM"
                            )
                            self.logger.debug(f"添加分组(元组): {group_name}, 股票数: {stock_count}")
                            
                        else:
                            # 其他格式，作为分组名处理
                            group_name = str(group)
                            
                            group_data = {
                                'name': group_name,
                                'stock_list': [],
                                'stock_count': 0,
                                'type': 'CUSTOM'
                            }
                            self.app_core.group_data.append(group_data)
                            
                            ui_manager.group_table.add_row(
                                group_name,
                                "未知",
                                "CUSTOM"
                            )
                            self.logger.debug(f"添加分组(字符串): {group_name}")
                            
                    except Exception as e:
                        self.logger.warning(f"处理分组数据失败: {e}, 数据: {group}")
                        continue
                        
                # 如果没有成功添加任何分组，显示默认信息
                if len(self.app_core.group_data) == 0:
                    self.app_core.group_data.append({
                        'name': '数据解析失败',
                        'stock_list': [],
                        'stock_count': 0,
                        'type': 'ERROR'
                    })
                    ui_manager.group_table.add_row("数据解析失败", "0", "ERROR")
                    
            else:
                # 添加默认提示行
                self.app_core.group_data.append({
                    'name': '暂无分组',
                    'stock_list': [],
                    'stock_count': 0,
                    'type': '-'
                })
                ui_manager.group_table.add_row("暂无分组", "0", "-")
                self.logger.info("未获取到分组数据，显示默认提示")
            
            # 重置光标位置并更新显示
            self.app_core.current_group_cursor = 0
            if ui_manager:
                await ui_manager.update_group_cursor()
            self.logger.info(f"加载用户分组完成，共 {len(self.app_core.group_data)} 个分组")
            
        except Exception as e:
            self.logger.warning(f"加载用户分组失败: {e}")
            # API调用失败时不更新连接状态，只显示错误信息
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.group_table:
                ui_manager.group_table.clear()
                self.app_core.group_data.clear()
                self.app_core.group_data.append({
                    'name': '加载失败',
                    'stock_list': [],
                    'stock_count': 0,
                    'type': 'ERROR'
                })
                ui_manager.group_table.add_row(
                    "加载失败",
                    "0",
                    "ERROR"
                )
                self.app_core.current_group_cursor = 0
                await ui_manager.update_group_cursor()
    
    async def refresh_user_groups(self) -> None:
        """刷新用户分组数据，用于添加/删除股票后更新stock_list"""
        try:
            self.logger.info("开始刷新用户分组数据...")
            
            # 重新加载用户分组数据
            await self.load_user_groups()
            
            # 更新分组预览信息
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager:
                await ui_manager.update_group_preview()
            
            self.logger.info("用户分组数据刷新完成")
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info("分组数据已刷新", "系统")
            
        except Exception as e:
            self.logger.error(f"刷新用户分组数据失败: {e}")
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info(f"刷新分组数据失败: {e}", "系统")
    
    async def handle_group_selection(self, row_index: int) -> None:
        """处理分组选择事件"""
        try:
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if not ui_manager or not ui_manager.group_table:
                return
                
            # 获取选中分组的信息
            group_row = ui_manager.group_table.get_row_at(row_index)
            if not group_row:
                return
                
            group_name = str(group_row[0])  # 分组名称
            
            if group_name in ["暂无分组", "加载失败", "连接未建立", "数据错误"]:
                # 显示提示信息
                if ui_manager.group_stocks_content:
                    ui_manager.group_stocks_content.update("[dim]无可用数据[/dim]")
                return
            
            # 从已缓存的分组数据中获取股票列表，避免重复API调用
            group_stocks = []
            
            # 在self.app_core.group_data中查找对应的分组数据
            for group_data in self.app_core.group_data:
                if group_data.get('name') == group_name:
                    group_stocks = group_data.get('stock_list', [])
                    self.logger.debug(f"从缓存获取分组 '{group_name}' 的股票列表，共 {len(group_stocks)} 只")
                    break
            
            # 如果缓存中没有找到，记录警告但不再调用API
            if not group_stocks:
                self.logger.warning(f"缓存中未找到分组 '{group_name}' 的股票数据，可能需要重新加载分组信息")
            
            # 更新分组股票显示
            if ui_manager.group_stocks_content:
                if group_stocks and len(group_stocks) > 0:
                    stock_list_text = f"[bold yellow]{group_name} - 股票列表[/bold yellow]\n\n"
                    for i, stock in enumerate(group_stocks[:10]):  # 最多显示10只股票
                        if isinstance(stock, dict):
                            stock_code = stock.get('code', 'Unknown')
                            stock_name = stock.get('name', '')
                            stock_list_text += f"{i+1}. {stock_code} {stock_name}\n"
                        else:
                            stock_list_text += f"{i+1}. {stock}\n"
                    
                    if len(group_stocks) > 10:
                        stock_list_text += f"\n[dim]... 还有 {len(group_stocks) - 10} 只股票[/dim]"
                    
                    ui_manager.group_stocks_content.update(stock_list_text)
                else:
                    ui_manager.group_stocks_content.update(f"[yellow]{group_name}[/yellow]\n\n[dim]该分组暂无股票[/dim]")
            
            self.logger.info(f"选择分组: {group_name}, 包含 {len(group_stocks) if group_stocks else 0} 只股票")
            if ui_manager.info_panel:
                await ui_manager.info_panel.log_info(f"选择分组: {group_name}, 包含 {len(group_stocks) if group_stocks else 0} 只股票", "分组选择")
            
        except Exception as e:
            self.logger.error(f"处理分组选择失败: {e}")
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.group_stocks_content:
                ui_manager.group_stocks_content.update("[red]加载分组股票失败[/red]")
    
    async def switch_to_group_stocks(self, group_data: Dict[str, Any]) -> None:
        """切换主界面监控的股票为指定分组的股票"""
        try:
            stock_list = group_data.get('stock_list', [])
            
            if stock_list:
                # 提取股票代码
                new_monitored_stocks = []
                for stock in stock_list:
                    if isinstance(stock, dict):
                        stock_code = stock.get('code', '')
                        if stock_code:
                            new_monitored_stocks.append(stock_code)
                    elif isinstance(stock, str):
                        new_monitored_stocks.append(stock)
                
                if new_monitored_stocks:
                    # 更新监控股票列表
                    self.app_core.monitored_stocks = new_monitored_stocks
                    
                    # 清空现有股票数据
                    self.app_core.stock_data.clear()
                    
                    # 重置股票光标位置
                    self.app_core.current_stock_cursor = 0
                    
                    # 重新加载股票表格
                    ui_manager = getattr(self.app_core.app, 'ui_manager', None)
                    if ui_manager:
                        await ui_manager.load_default_stocks()
                    
                    # 等待一个事件循环，确保UI更新完成
                    await asyncio.sleep(0.1)

                    # 如果处于实时模式，需要重新订阅新股票
                    data_manager = getattr(self.app_core.app, 'data_manager', None)
                    if data_manager:
                        # 检查当前是否处于实时模式
                        if self.app_core.refresh_mode == "实时模式":
                            self.logger.info("检测到实时模式，重新启动数据订阅...")
                            # 停止当前的刷新任务
                            if data_manager.refresh_timer:
                                data_manager.refresh_timer.cancel()
                                try:
                                    await data_manager.refresh_timer
                                except asyncio.CancelledError:
                                    pass
                                data_manager.refresh_timer = None
                            
                            # 重新启动数据刷新（这会重新订阅新的股票列表）
                            await data_manager.start_data_refresh()
                        else:
                            # 快照模式只需要刷新数据
                            await data_manager.refresh_stock_data()
                    
                    self.logger.info(f"已切换到分组 '{group_data['name']}' 的股票，共 {len(new_monitored_stocks)} 只")
                else:
                    self.logger.warning(f"分组 '{group_data['name']}' 中没有有效的股票代码")
            else:
                self.logger.warning(f"分组 '{group_data['name']}' 为空")
                
        except Exception as e:
            self.logger.error(f"切换到分组股票失败: {e}")
    
    async def add_stock_to_group(self, group_name: str, stock_code: str) -> bool:
        """将股票添加到指定分组"""
        try:
            success = self.futu_market.modify_user_security(
                group_name, 
                [stock_code], 
                "ADD"
            )
            if success:
                self.logger.info(f"股票 {stock_code} 已添加到分组 {group_name}")
                return True
            else:
                self.logger.warning(f"股票 {stock_code} 添加到分组 {group_name} 失败")
                return False
        except Exception as e:
            self.logger.error(f"添加股票到分组失败: {e}")
            return False
    
    async def remove_stock_from_group(self, group_name: str, stock_code: str) -> bool:
        """从指定分组中删除股票"""
        try:
            success = self.futu_market.modify_user_security(
                group_name, 
                [stock_code], 
                "DEL"
            )
            if success:
                self.logger.info(f"股票 {stock_code} 已从分组 {group_name} 中删除")
                return True
            else:
                self.logger.warning(f"股票 {stock_code} 从分组 {group_name} 删除失败")
                return False
        except Exception as e:
            self.logger.error(f"从分组删除股票失败: {e}")
            return False
    
    async def load_user_positions(self) -> None:
        """加载用户持仓数据"""
        try:
            # 需要引入FutuTrade来获取持仓数据
            # 引用app中的futu_trade实例
            futu_trade = getattr(self.app_core.app, 'futu_trade', None)
            if not futu_trade:
                self.logger.error("FutuTrade实例未找到")
                return
            
            # 在线程池中执行同步的富途API调用
            loop = asyncio.get_event_loop()
            user_positions = await loop.run_in_executor(
                None, 
                futu_trade.get_position_list
            )
            
            # 清空现有持仓数据
            self.app_core.position_data.clear()
            
            # 处理持仓数据
            if user_positions:
                for position in user_positions:
                    if isinstance(position, dict):
                        # 添加调试日志查看原始数据的所有字段
                        #self.logger.debug(f"原始持仓数据字段: {list(position.keys())}")
                        self.logger.debug(f"原始持仓数据: code={position.get('code')}, name={position.get('name')}, stock_name={position.get('stock_name')}")

                        position_data = {
                            'stock_code': position.get('code', ''),
                            # 尝试多个字段名，因为富途API可能返回不同的字段名
                            'stock_name': position.get('stock_name') or position.get('name', ''),
                            'qty': position.get('qty', 0),
                            'can_sell_qty': position.get('can_sell_qty', 0),
                            'market_val': position.get('market_val', 0),
                            'cost_price': position.get('cost_price', 0),
                            'nominal_price': position.get('nominal_price', 0),
                            'pl_val': position.get('pl_val', 0),
                            'pl_ratio': position.get('pl_ratio', 0),
                            'currency': position.get('currency', 'HKD')
                        }
                        self.app_core.position_data.append(position_data)
            
            self.logger.debug(f"加载用户持仓完成，共 {len(self.app_core.position_data)} 只股票")
            
        except Exception as e:
            self.logger.error(f"加载用户持仓失败: {e}")
            # 添加错误提示数据
            self.app_core.position_data.clear()
            self.app_core.position_data.append({
                'stock_code': '加载失败',
                'stock_name': '请检查富途连接',
                'qty': 0,
                'can_sell_qty': 0,
                'market_val': 0,
                'cost_price': 0,
                'nominal_price': 0,
                'pl_val': 0,
                'pl_ratio': 0,
                'currency': 'HKD'
            })

    async def load_user_orders(self) -> None:
        """加载用户订单数据到 app_core.order_data"""
        self.logger.debug("开始加载用户订单数据")

        try:
            # 引用app中的futu_trade实例
            futu_trade = getattr(self.app_core.app, 'futu_trade', None)
            if not futu_trade:
                self.logger.error("FutuTrade实例未找到")
                return

            # 在线程池中执行同步的富途API调用
            loop = asyncio.get_event_loop()
            user_orders = await loop.run_in_executor(
                None,
                futu_trade.get_order_list
            )

            # 处理订单数据并保存到 app_core.order_data
            if user_orders:
                # 清空现有订单数据 - 只在确认有有效数据时才清空
                self.app_core.order_data.clear()

                for order in user_orders:
                    try:
                        if isinstance(order, dict):
                            # 标准化订单数据结构
                            # 注意：富途API返回的字段是 stock_name，不是 name
                            order_data = {
                                'order_id': str(order.get('order_id', '')),
                                'code': order.get('code', ''),
                                'name': order.get('stock_name', ''),  # 修正：使用 stock_name
                                'trd_side': order.get('trd_side', ''),
                                'order_status': order.get('order_status', ''),
                                'qty': order.get('qty', 0),
                                'price': order.get('price', 0),
                                'dealt_qty': order.get('dealt_qty', 0),
                                'dealt_avg_price': order.get('dealt_avg_price', 0),
                                'create_time': order.get('create_time', ''),
                                'updated_time': order.get('updated_time', ''),
                                'currency': order.get('currency', ''),
                                'order_type': order.get('order_type', '')
                            }
                            self.app_core.order_data.append(order_data)
                            self.logger.debug(f"添加订单到order_data: {order_data['order_id']} {order_data['code']} {order_data['name']}")

                    except Exception as e:
                        self.logger.error(f"处理订单数据失败: {e}, 订单数据: {order}")
                        continue

                self.logger.info(f"加载用户订单完成，共 {len(user_orders)} 条订单保存到 app_core.order_data")
            else:
                # API返回None或空列表时，保留现有数据不清空
                self.logger.warning(f"API返回空订单列表，保留现有数据({len(self.app_core.order_data)}条)")

        except Exception as e:
            self.logger.error(f"加载用户订单失败: {e}")
            # API调用失败时保留现有数据，只在日志中记录错误
            # 不再清空和添加错误提示数据，避免覆盖正常数据
            self.logger.warning(f"订单数据刷新失败，保留现有数据({len(self.app_core.order_data)}条)")

    async def refresh_user_positions(self) -> None:
        """刷新用户持仓数据"""
        try:
            self.logger.info("开始刷新用户持仓数据...")
            
            # 重新加载用户持仓数据
            await self.load_user_positions()
            
            # 更新UI显示
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager:
                await ui_manager.update_position_display()
            
            self.logger.info("用户持仓数据刷新完成")
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info("持仓数据已刷新", "系统")
            
        except Exception as e:
            self.logger.error(f"刷新用户持仓数据失败: {e}")
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info(f"刷新持仓数据失败: {e}", "系统")
    
    async def handle_position_selection(self, row_index: int) -> None:
        """处理持仓选择事件"""
        try:
            if row_index < 0 or row_index >= len(self.app_core.position_data):
                return

            selected_position = self.app_core.position_data[row_index]
            stock_code = selected_position.get('stock_code', '')

            # 记录选择的持仓
            self.logger.info(f"选择持仓: {stock_code}")

            # 更新持仓详情显示
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info(f"选择持仓: {stock_code}", "持仓选择")

        except Exception as e:
            self.logger.error(f"处理持仓选择失败: {e}")

    async def refresh_user_orders(self) -> None:
        """刷新用户订单数据"""
        try:
            self.logger.info("开始刷新用户订单数据...")

            # 重新加载用户订单数据
            await self.load_user_orders()

            # 更新UI显示
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager:
                await ui_manager.update_orders_table()

            self.logger.info("用户订单数据刷新完成")
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info("订单数据已刷新", "系统")

        except Exception as e:
            self.logger.error(f"刷新用户订单数据失败: {e}")
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager and ui_manager.info_panel:
                await ui_manager.info_panel.log_info(f"刷新订单数据失败: {e}", "系统")

    async def calculate_position_summary(self) -> Dict[str, Any]:
        """计算持仓汇总信息"""
        try:
            if not self.app_core.position_data:
                return {
                    'total_market_val': 0,
                    'total_pl_val': 0,
                    'total_pl_ratio': 0,
                    'position_count': 0
                }
            
            total_market_val = sum(pos.get('market_val', 0) for pos in self.app_core.position_data)
            total_pl_val = sum(pos.get('pl_val', 0) for pos in self.app_core.position_data)
            total_pl_ratio = (total_pl_val / (total_market_val - total_pl_val)) * 100 if total_market_val > total_pl_val else 0
            position_count = len(self.app_core.position_data)
            
            return {
                'total_market_val': total_market_val,
                'total_pl_val': total_pl_val,
                'total_pl_ratio': total_pl_ratio,
                'position_count': position_count
            }
            
        except Exception as e:
            self.logger.error(f"计算持仓汇总失败: {e}")
            return {
                'total_market_val': 0,
                'total_pl_val': 0,
                'total_pl_ratio': 0,
                'position_count': 0
            }