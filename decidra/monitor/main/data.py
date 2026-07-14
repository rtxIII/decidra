"""
DataManager - 股票数据和API管理模块

负责股票数据获取、API调用管理、数据刷新和格式转换
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Dict, Optional, Any

from ...base.monitor import StockData, MarketStatus, ConnectionStatus
from ...modules.futu_market import FutuMarket
from ...base.futu_class import MarketSnapshot
from ...utils.global_vars import get_logger
from ...utils.global_vars import PATH_DATA

SNAPSHOT_REFRESH_INTERVAL = 300
REALTIME_REFRESH_INTERVAL = 1
ORDER_REFRESH_INTERVAL = 5  # 订单数据刷新间隔（秒）
CACHE_EXPIRY_HOURS = 8
BASICINFO_CACHE_FILE = "stock_basicinfo_cache.json"

# 全局交易模式配置
TRADING_MODE_SIMULATION = "模拟交易"
TRADING_MODE_REAL = "真实交易"
CURRENT_TRADING_MODE = TRADING_MODE_SIMULATION  # 默认为模拟交易模式


class DataManager:
    """
    数据管理器
    负责股票数据获取、API调用管理和数据处理
    """

    def __init__(self, app_core, futu_market: FutuMarket, futu_trade=None):
        """初始化数据管理器"""
        self.app_core = app_core
        self.logger = get_logger(__name__)

        # 富途市场实例
        self.futu_market = futu_market

        # 富途交易实例
        self.futu_trade = futu_trade

        # 定时器
        self.refresh_timer: Optional[asyncio.Task] = None
        self.market_status_poller: Optional[asyncio.Task] = None
        self.user_refresh_timer: Optional[asyncio.Task] = None

        # 全局市场状态缓存
        self._global_market_state_cache = None
        self._market_status_cache_timestamp = 0.0
        self._market_status_cache_ttl = 30.0  # 缓存有效期30秒

        self.logger.info("DataManager 初始化完成")

    def get_trading_mode(self) -> str:
        """获取当前交易模式"""
        global CURRENT_TRADING_MODE
        return CURRENT_TRADING_MODE

    def set_trading_mode(self, mode: str) -> bool:
        """设置交易模式

        Args:
            mode: 交易模式，必须是 TRADING_MODE_SIMULATION 或 TRADING_MODE_REAL

        Returns:
            bool: 设置是否成功
        """
        global CURRENT_TRADING_MODE
        if mode in [TRADING_MODE_SIMULATION, TRADING_MODE_REAL]:
            CURRENT_TRADING_MODE = mode
            self.logger.info(f"交易模式已切换为: {mode}")
            return True
        else:
            self.logger.error(f"无效的交易模式: {mode}")
            return False

    def is_simulation_mode(self) -> bool:
        """判断是否为模拟交易模式"""
        return self.get_trading_mode() == TRADING_MODE_SIMULATION

    def toggle_trading_mode(self) -> str:
        """切换交易模式

        Returns:
            str: 切换后的交易模式
        """
        current_mode = self.get_trading_mode()
        new_mode = TRADING_MODE_REAL if current_mode == TRADING_MODE_SIMULATION else TRADING_MODE_SIMULATION
        self.set_trading_mode(new_mode)
        return new_mode

    def get_trading_mode_constants(self) -> tuple:
        """获取交易模式常量

        Returns:
            tuple: (TRADING_MODE_SIMULATION, TRADING_MODE_REAL)
        """
        return TRADING_MODE_SIMULATION, TRADING_MODE_REAL

    async def initialize_data_managers(self) -> None:
        """初始化数据管理器"""
        try:
            # 主动建立富途连接
            try:
                self.logger.info("正在连接富途API...")
                loop = asyncio.get_event_loop()
                
                # 在线程池中执行连接操作
                connect_success = await loop.run_in_executor(
                    None, 
                    self.futu_market.client.connect
                )
                
                if connect_success:
                    self.app_core.connection_status = ConnectionStatus.CONNECTED
                    self.logger.info("富途API连接成功")
                    # 向信息面板显示连接状态
                    if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                        await self.app_core.app.ui_manager.info_panel.log_info("富途API连接成功", "连接状态")
                    
                    # 连接成功后立即加载股票基本信息
                    await self.load_stock_basicinfo()
                    
                    # 启动市场状态轮询任务
                    await self.start_market_status_poller()
                else:
                    self.app_core.connection_status = ConnectionStatus.DISCONNECTED
                    self.logger.warning("富途API连接失败")
                    
            except Exception as e:
                self.app_core.connection_status = ConnectionStatus.ERROR
                self.logger.error(f"富途API连接失败: {e}")
            
            
        except Exception as e:
            self.logger.error(f"数据管理器初始化失败: {e}")
            self.app_core.connection_status = ConnectionStatus.ERROR
    
    async def attempt_reconnect(self) -> bool:
        """尝试重新连接富途API"""
        if self.app_core._reconnect_attempts >= self.app_core._max_reconnect_attempts:
            self.logger.error(f"超过最大重连次数 {self.app_core._max_reconnect_attempts}")
            return False
            
        self.app_core._reconnect_attempts += 1
        self.logger.info(f"尝试重连富途API (第 {self.app_core._reconnect_attempts} 次)")
        
        try:
            # 关闭旧连接
            if hasattr(self.futu_market, 'close'):
                self.futu_market.close()
            
            # 等待一段时间后重新创建连接
            await asyncio.sleep(2.0)
            
            # 重新创建富途市场实例
            self.futu_market = FutuMarket()
            self.futu_market._is_shared_instance = True
            
            # 检查新连接状态
            loop = asyncio.get_event_loop()
            connection_state = await loop.run_in_executor(
                None, 
                self.futu_market.get_connection_state
            )
            
            if connection_state[0]:
                self.app_core.connection_status = ConnectionStatus.CONNECTED
                self.app_core._reconnect_attempts = 0  # 重置重连计数
                self.logger.info("富途API重连成功")
                return True
            else:
                self.app_core.connection_status = ConnectionStatus.DISCONNECTED
                self.logger.warning(f"富途API重连失败: {connection_state[1]}")
                return False
                
        except Exception as e:
            self.logger.error(f"重连过程中出错: {e}")
            self.app_core.connection_status = ConnectionStatus.ERROR
            return False
    
    def get_cached_global_market_state(self):
        """获取缓存的全局市场状态"""
        current_time = time.time()
        
        # 检查缓存是否有效
        if (self._global_market_state_cache is not None and 
            current_time - self._market_status_cache_timestamp < self._market_status_cache_ttl):
            return self._global_market_state_cache
        
        return None
    
    def update_global_market_state_cache(self, global_state):
        """更新全局市场状态缓存"""
        self._global_market_state_cache = global_state
        self._market_status_cache_timestamp = time.time()
        self.logger.debug(f"全局市场状态缓存已更新: {global_state}")
    
    def get_market_status_by_prefix(self, market_prefix: str) -> str:
        """根据市场前缀获取特定市场状态
        
        Args:
            market_prefix: 市场前缀 ('HK', 'US', 'SH', 'SZ')
            
        Returns:
            str: 市场状态字符串，如 'OPEN', 'CLOSE', 'MORNING' 等
        """
        cached_state = self.get_cached_global_market_state()
        
        if cached_state is None:
            return 'UNKNOWN'
        
        market_status_map = {
            'HK': cached_state.market_hk,
            'US': cached_state.market_us, 
            'SH': cached_state.market_sh,
            'SZ': cached_state.market_sz
        }
        
        return market_status_map.get(market_prefix, 'UNKNOWN') or 'CLOSE'
    
    async def start_market_status_poller(self):
        """启动市场状态轮询任务"""
        if self.market_status_poller and not self.market_status_poller.done():
            self.logger.info("市场状态轮询任务已在运行")
            return
        
        self.market_status_poller = asyncio.create_task(self.market_status_polling_loop())
        self.logger.info("市场状态轮询任务已启动")
    
    async def market_status_polling_loop(self):
        """市场状态轮询循环"""
        while True:
            try:
                if self.app_core.connection_status == ConnectionStatus.CONNECTED:
                    # 获取全局市场状态并更新缓存
                    loop = asyncio.get_event_loop()
                    global_state = await loop.run_in_executor(
                        None,
                        self.futu_market.get_global_state
                    )
                    
                    if global_state:
                        self.update_global_market_state_cache(global_state)
                        self.logger.debug("市场状态轮询更新成功")
                    else:
                        self.logger.warning("市场状态轮询获取数据为空")
                
                # 每30秒轮询一次
                await asyncio.sleep(self._market_status_cache_ttl)
                
            except asyncio.CancelledError:
                self.logger.info("市场状态轮询任务已取消")
                break
            except Exception as e:
                self.logger.error(f"市场状态轮询错误: {e}")
                # 出错时等待更长时间再重试
                await asyncio.sleep(60)
    async def detect_market_status(self) -> MarketStatus:
        """检测市场状态 - 优先使用缓存，缓存失效时使用富途API"""
        try:
            if self.app_core.connection_status != ConnectionStatus.CONNECTED:
                self.logger.warning("富途API未连接，使用本地时间判断市场状态")
                return self._detect_market_status_fallback()
            
            # 优先从缓存获取全局市场状态
            global_state = self.get_cached_global_market_state()
            
            if global_state is None:
                # 缓存失效，使用富途API获取全局市场状态
                self.logger.debug("市场状态缓存失效，从API重新获取")
                loop = asyncio.get_event_loop()
                global_state = await loop.run_in_executor(
                    None,
                    self.futu_market.get_global_state
                )
                
                # 更新缓存
                if global_state:
                    self.update_global_market_state_cache(global_state)
            else:
                self.logger.debug("使用缓存的市场状态数据")
            
            if global_state:
                # 检查监控股票涉及的市场状态
                markets_open = 0
                markets_total = 0
                open_markets = []  # 记录开市的市场名称
                
                for stock_code in self.app_core.monitored_stocks:
                    market_prefix = stock_code.split('.')[0]  # HK, US, SH, SZ
                    
                    if market_prefix == 'HK':
                        markets_total += 1
                        # 检查港股市场状态
                        hk_status = global_state.market_hk or 'CLOSE'
                        # 港股闭市状态：CLOSED, CLOSE, REST, HALT等
                        # 港股开盘状态：除了明确的闭市状态外，其他状态都可能表示某种形式的开盘
                        closed_statuses = ['CLOSED', 'CLOSE', 'REST', 'HALT', 'SUSPEND']
                        if hk_status not in closed_statuses:
                            markets_open += 1
                            if 'HK' not in open_markets:
                                open_markets.append('HK')
                            self.logger.debug(f"港股市场开盘状态: {hk_status}")
                        else:
                            self.logger.debug(f"港股市场闭市状态: {hk_status}")
                            
                    elif market_prefix == 'US':
                        markets_total += 1
                        # 检查美股市场状态
                        us_status = global_state.market_us or 'CLOSE'
                        # 美股闭市状态：CLOSED, CLOSE, REST, HALT等
                        closed_statuses = ['CLOSED', 'CLOSE', 'REST', 'HALT', 'SUSPEND', 'PRE_MARKET_BEGIN', 'PRE_MARKET_END']
                        if us_status not in closed_statuses:
                            markets_open += 1
                            if 'US' not in open_markets:
                                open_markets.append('US')
                            self.logger.debug(f"美股市场开盘状态: {us_status}")
                        else:
                            self.logger.debug(f"美股市场闭市状态: {us_status}")
                            
                    elif market_prefix == 'SH':
                        markets_total += 1
                        # 检查上海市场状态
                        sh_status = global_state.market_sh or 'CLOSE'
                        # 上海市场闭市状态
                        closed_statuses = ['CLOSED', 'CLOSE', 'REST', 'HALT', 'SUSPEND']
                        if sh_status not in closed_statuses:
                            markets_open += 1
                            if 'SH' not in open_markets:
                                open_markets.append('SH')
                            self.logger.debug(f"上海市场开盘状态: {sh_status}")
                        else:
                            self.logger.debug(f"上海市场闭市状态: {sh_status}")
                            
                    elif market_prefix == 'SZ':
                        markets_total += 1
                        # 检查深圳市场状态
                        sz_status = global_state.market_sz or 'CLOSE'
                        # 深圳市场闭市状态
                        closed_statuses = ['CLOSED', 'CLOSE', 'REST', 'HALT', 'SUSPEND']
                        if sz_status not in closed_statuses:
                            markets_open += 1
                            if 'SZ' not in open_markets:
                                open_markets.append('SZ')
                            self.logger.debug(f"深圳市场开盘状态: {sz_status}")
                        else:
                            self.logger.debug(f"深圳市场闭市状态: {sz_status}")
                
                # 向信息面板显示市场状态
                if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                    if open_markets:
                        open_markets_text = ", ".join(open_markets)
                        await self.app_core.app.ui_manager.info_panel.log_info(f"市场状态: {markets_open}/{markets_total} 个市场开盘 (开市: {open_markets_text})", "市场状态")
                    else:
                        await self.app_core.app.ui_manager.info_panel.log_info(f"市场状态: {markets_open}/{markets_total} 个市场开盘 (全部闭市)", "市场状态")
                
                # 更新开市市场信息到app_core
                self.app_core.open_markets = open_markets.copy()
                
                # 如果有任何监控的市场在开盘，则认为是开盘状态
                if markets_open > 0:
                    self.logger.info(f"市场状态检测：{markets_open}/{markets_total} 个市场开盘")
                    return MarketStatus.OPEN
                else:
                    self.logger.info(f"市场状态检测：所有监控市场均已闭市")
                    return MarketStatus.CLOSE
            else:
                self.logger.warning("富途API返回的全局状态数据格式异常，使用fallback方法")
                return self._detect_market_status_fallback()
                
        except Exception as e:
            self.logger.error(f"检测市场状态失败: {e}，使用fallback方法")
            return self._detect_market_status_fallback()
    
    def _detect_market_status_fallback(self) -> MarketStatus:
        """备用市场状态检测方法 - 基于时间和工作日判断"""
        try:
            current_time = datetime.now()
            hour = current_time.hour
            minute = current_time.minute
            weekday = current_time.weekday()  # 0=周一, 6=周日
            
            # 周末必定闭市
            if weekday >= 5:  # 周六和周日
                return MarketStatus.CLOSE
            
            # 简单的交易时间判断（涵盖港股和A股的主要交易时间）
            # 港股：9:30-12:00, 13:00-16:00
            # A股：9:30-11:30, 13:00-15:00
            morning_open = (9 < hour < 12) or (hour == 9 and minute >= 30)
            afternoon_open = (13 <= hour < 16)
            
            if morning_open or afternoon_open:
                return MarketStatus.OPEN
            else:
                return MarketStatus.CLOSE
                
        except Exception as e:
            self.logger.error(f"备用市场状态检测失败: {e}")
            return MarketStatus.CLOSE
    
    async def start_data_refresh(self) -> None:
        """启动数据刷新"""
        try:
            # 判断市场状态并设置刷新模式
            market_status = await self.detect_market_status()
            
            # 同步更新app_core中的市场状态
            self.app_core.market_status = market_status
            # 注意：这里需要从detect_market_status返回开市市场信息，暂时先设为空
            
            if market_status == MarketStatus.OPEN:
                self.app_core.refresh_mode = "实时模式"
                # 启动实时数据订阅
                await self.start_realtime_subscription()
            else:
                self.app_core.refresh_mode = "快照模式"
                # 启动快照数据刷新
                await self.start_snapshot_refresh()
            
            self.logger.info(f"数据刷新启动: {self.app_core.refresh_mode}, 市场状态: {market_status.value}")
            # 向信息面板显示数据刷新模式变化
            if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                await self.app_core.app.ui_manager.info_panel.log_info(f"数据刷新启动: {self.app_core.refresh_mode}", "系统")
            
            # 更新状态显示
            await self.app_core.update_status_display()

            # 启动用户数据刷新
            await self.start_user_refresh()
            
        except Exception as e:
            self.logger.error(f"启动数据刷新失败: {e}")
    
    async def start_realtime_subscription(self) -> None:
        """启动实时数据订阅"""
        try:
            if self.app_core.connection_status == ConnectionStatus.CONNECTED:
                # 首先取消所有之前的订阅，避免冲突
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self.futu_market.unsubscribe_all
                )
                self.logger.info("已取消所有之前的订阅")
                # 订阅实时数据
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self.futu_market.subscribe,
                    self.app_core.monitored_stocks,
                    ["quote"],  # 订阅类型：实时报价
                    True,       # is_first_push
                    True        # is_unlimit_push
                )
                if success:
                    self.logger.info("实时数据订阅成功")
                    # 启动实时数据获取循环
                    self.refresh_timer = asyncio.create_task(self.realtime_data_loop())
                    self.logger.info("实时数据获取循环启动")
                else:
                    raise Exception("订阅失败")
        except Exception as e:
            self.logger.error(f"实时数据订阅失败: {e}")
            # 降级到快照模式
            await self.start_snapshot_refresh()
    
    async def realtime_data_loop(self) -> None:
        """实时数据获取循环"""
        while True:
            try:
                # 通过get_stock_quote获取实时报价
                await self.fetch_realtime_quotes()
                # 实时模式更新频率更高，每REALTIME_REFRESH_INTERVAL秒更新一次
                await asyncio.sleep(REALTIME_REFRESH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"实时数据获取错误: {e}")
                await asyncio.sleep(REALTIME_REFRESH_INTERVAL)
    
    async def fetch_realtime_quotes(self) -> None:
        """获取实时报价数据"""
        try:
            if not self.app_core.monitored_stocks:
                return
            
            self.logger.debug(f"获取 {len(self.app_core.monitored_stocks)} 只股票的实时报价")
            
            # 调用get_stock_quote获取实时报价
            loop = asyncio.get_event_loop()
            quotes = await loop.run_in_executor(
                None,
                self.futu_market.get_stock_quote,
                self.app_core.monitored_stocks
            )
            
            if quotes:
                self.app_core.connection_status = ConnectionStatus.CONNECTED
                updated_count = 0
                
                for quote in quotes:
                    if hasattr(quote, 'code'):
                        stock_code = quote.code
                        # 转换报价数据为StockData格式
                        stock_info = self.convert_quote_to_stock_data(quote)
                        if stock_info is not None:
                            self.app_core.stock_data[stock_code] = stock_info
                            updated_count += 1
                            self.logger.debug(f"更新实时数据: {stock_code} - {stock_info.current_price}")
                
                # 更新UI
                await self.app_core.app.ui_manager.update_stock_table()
                self.logger.debug(f"实时数据更新成功，共更新 {updated_count} 只股票")
            else:
                self.logger.warning("获取实时报价返回空数据")
                
        except Exception as e:
            self.logger.error(f"获取实时报价失败: {e}")
    
    def convert_quote_to_stock_data(self, quote) -> Optional[StockData]:
        """将富途报价数据转换为标准StockData格式"""
        try:
            # 获取价格数据
            current_price = getattr(quote, 'cur_price', getattr(quote, 'last_price', 0))
            prev_close = getattr(quote, 'prev_close_price', 0)
            
            if current_price <= 0:
                self.logger.warning(f"股票 {quote.code} 价格数据异常: {current_price}")
                return None
                
            if prev_close <= 0:
                prev_close = current_price
                
            # 计算涨跌幅和涨跌额
            change_rate = 0.0
            if prev_close > 0:
                change_rate = ((current_price - prev_close) / prev_close) * 100
            change_amount = current_price - prev_close
            
            # 从缓存获取股票名称
            basic_info = self.get_stock_basicinfo_from_cache(quote.code)
            stock_name = basic_info.get('name', quote.code) if basic_info else quote.code
            
            return StockData(
                code=quote.code,
                name=stock_name,
                current_price=current_price,
                open_price=getattr(quote, 'open_price', current_price),
                prev_close=prev_close,
                change_rate=change_rate,
                change_amount=change_amount,
                volume=max(0, getattr(quote, 'volume', 0)),
                turnover=getattr(quote, 'turnover', 0),
                high_price=getattr(quote, 'high_price', current_price),
                low_price=getattr(quote, 'low_price', current_price),
                update_time=datetime.now(),
                market_status=MarketStatus.OPEN
            )
            
        except Exception as e:
            self.logger.error(f"转换报价数据时发生错误: {e}")
            return None
    
    async def start_snapshot_refresh(self) -> None:
        """启动快照数据刷新"""
        # 检查是否已有刷新任务在运行
        if self.refresh_timer and not self.refresh_timer.done():
            self.logger.info("快照数据刷新已在运行，跳过重复启动")
            return
            
        # 取消现有任务（如果存在）
        if self.refresh_timer:
            self.refresh_timer.cancel()
            try:
                await self.refresh_timer
            except asyncio.CancelledError:
                pass
        
        # 创建定时刷新任务
        self.refresh_timer = asyncio.create_task(self.snapshot_refresh_loop())
        self.logger.info("快照数据刷新启动")
    
    async def snapshot_refresh_loop(self) -> None:
        """快照数据刷新循环"""
        while True:
            try:
                await self.refresh_stock_data()
                await asyncio.sleep(SNAPSHOT_REFRESH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"快照数据刷新错误: {e}")
                await asyncio.sleep(SNAPSHOT_REFRESH_INTERVAL)
    
    async def refresh_stock_data(self) -> None:
        """刷新股票数据"""
        try:
            if not self.app_core.monitored_stocks:
                self.logger.warning("没有监控的股票，跳过数据刷新")
                return
            
            self.logger.info(f"开始刷新 {len(self.app_core.monitored_stocks)} 只股票的数据")
            
            # 直接调用API获取实时行情数据
            loop = asyncio.get_event_loop()
            market_snapshots = await loop.run_in_executor(
                None,
                self.futu_market.get_market_snapshot,
                self.app_core.monitored_stocks
            )
            
            # 转换数据格式并更新
            if market_snapshots:
                # 更新连接状态为已连接
                self.app_core.connection_status = ConnectionStatus.CONNECTED
                
                updated_count = 0
                for snapshot in market_snapshots:
                    self.logger.debug(f'股票数据: {snapshot.code} {snapshot}')
                    # 修复：snapshot现在是MarketSnapshot对象，不是字典
                    if hasattr(snapshot, 'code'):
                        stock_code = snapshot.code
                        stock_info = self.convert_snapshot_to_stock_data(snapshot)
                        # 只有转换成功的数据才存储
                        if stock_info is not None:
                            self.app_core.stock_data[stock_code] = stock_info
                            updated_count += 1
                            self.logger.debug(f"更新股票数据: {stock_code} - {stock_info.current_price}")
                        else:
                            self.logger.warning(f"股票 {stock_code} 数据转换失败")
                
                await self.app_core.app.ui_manager.update_stock_table()
                
                self.logger.info(f"股票数据刷新成功，共更新 {updated_count} 只股票")
                # 向信息面板显示数据刷新信息
                if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                    await self.app_core.app.ui_manager.info_panel.log_info(f"股票数据已更新: {updated_count} 只股票", "数据刷新")
            else:
                # API调用返回空数据，可能是连接问题
                self.app_core.connection_status = ConnectionStatus.DISCONNECTED
                self.logger.warning("API调用返回空数据，可能存在连接问题")
            
        except Exception as e:
            # API调用失败，更新连接状态
            self.app_core.connection_status = ConnectionStatus.ERROR
            self.logger.error(f"刷新股票数据失败: {e}")
            # 尝试重连
            if self.app_core.connection_status == ConnectionStatus.ERROR:
                self.logger.info("尝试重新连接...")
                reconnect_success = await self.attempt_reconnect()
                if reconnect_success:
                    self.logger.info("重连成功，重新尝试获取数据")
                    # 向信息面板显示重连成功信息
                    if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                        await self.app_core.app.ui_manager.info_panel.log_info("富途API重连成功", "连接状态")
                    # 递归重试一次
                    try:
                        await self.refresh_stock_data()
                    except Exception as retry_e:
                        self.logger.error(f"重连后重试失败: {retry_e}")
    
    def convert_snapshot_to_stock_data(self, snapshot: MarketSnapshot) -> StockData:
        """将富途快照数据转换为标准StockData格式"""
        try:
            # 数据清理和验证
            current_price = snapshot.last_price
            prev_close = snapshot.prev_close_price
            
            if current_price <= 0:
                self.logger.warning(f"股票 {snapshot.code} 价格数据异常: {current_price}, 跳过此次更新")
                return None
                
            if prev_close <= 0:
                prev_close = current_price  # 如果昨收价异常，使用当前价格
                
            # 计算涨跌幅，并限制在合理范围内
            change_rate = 0.0
            if prev_close > 0:
                change_rate = ((current_price - prev_close) / prev_close) * 100
            
            # 计算涨跌额
            change_amount = current_price - prev_close
            
            # 从snapshot获取股票名称，如果没有则使用股票代码
            basic_info = self.get_stock_basicinfo_from_cache(snapshot.code)
            stock_name = basic_info.get('name', snapshot.code)
            
            return StockData(
                code=snapshot.code,
                name=stock_name,
                current_price=current_price,
                open_price=snapshot.open_price,
                prev_close=prev_close,
                change_rate=change_rate,
                change_amount=change_amount,
                volume=max(0, snapshot.volume),  # 确保成交量非负
                turnover=snapshot.turnover,
                high_price=snapshot.high_price,
                low_price=snapshot.low_price,
                update_time=datetime.now(),
                market_status=MarketStatus.OPEN
            )
            
        except Exception as e:
            self.logger.error(f"转换股票数据时发生错误: {e}")
            return None
    
    async def on_realtime_data_received(self, data: Dict[str, Any]) -> None:
        """处理实时数据回调"""
        try:
            # 处理实时推送数据
            stock_code = data.get('stock_code')
            if stock_code in self.app_core.monitored_stocks:
                # 更新股票数据
                stock_info = StockData(
                    code=stock_code,
                    name=data.get('name', ''),
                    current_price=data.get('price', 0.0),
                    open_price=data.get('open_price', 0.0),
                    prev_close=data.get('prev_close', 0.0),
                    change_rate=data.get('change_rate', 0.0),
                    change_amount=data.get('change_amount', 0.0),
                    volume=data.get('volume', 0),
                    turnover=data.get('turnover', 0.0),
                    high_price=data.get('high_price', 0.0),
                    low_price=data.get('low_price', 0.0),
                    update_time=datetime.now(),
                    market_status=MarketStatus.OPEN
                )
                
                self.app_core.stock_data[stock_code] = stock_info
                
        except Exception as e:
            self.logger.error(f"处理实时数据失败: {e}")
    
    async def cleanup(self) -> None:
        """清理数据管理器资源"""
        try:
            # 停止刷新定时器
            if self.refresh_timer:
                self.refresh_timer.cancel()
                self.refresh_timer = None
            
            # 停止市场状态轮询任务
            if self.market_status_poller:
                self.market_status_poller.cancel()
                try:
                    await self.market_status_poller
                except asyncio.CancelledError:
                    pass
                self.market_status_poller = None
                self.logger.debug("市场状态轮询任务已停止")

            # 停止用户数据刷新定时器（订单和持仓）
            if self.user_refresh_timer:
                self.user_refresh_timer.cancel()
                try:
                    await self.user_refresh_timer
                except asyncio.CancelledError:
                    pass
                self.user_refresh_timer = None
                self.logger.debug("用户数据定时刷新任务已停止")

            # 清理缓存
            self._global_market_state_cache = None
            self._market_status_cache_timestamp = 0.0
            

                
            self.logger.debug("DataManager 清理完成")

        except Exception as e:
            self.logger.error(f"DataManager 清理失败: {e}")

    async def refresh_order_data(self) -> None:
        """刷新订单数据并更新UI"""
        try:
            self.logger.debug("开始刷新订单数据")

            # 先通过 UserDataManager 加载订单数据到 app_core.order_data
            group_manager = getattr(self.app_core.app, 'group_manager', None)
            if group_manager:
                await group_manager.load_user_orders()
            else:
                self.logger.warning("UserDataManager 未初始化，无法刷新订单数据")
                return

            # 然后委托给 UIManager 更新表格UI
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager:
                await ui_manager.update_orders_table()
            else:
                self.logger.warning("UIManager 未初始化，跳过更新订单表格UI")

            self.logger.debug(f"订单数据刷新完成，共 {len(self.app_core.order_data)} 条订单")

        except Exception as e:
            self.logger.error(f"刷新订单数据失败: {e}")

    async def refresh_position_data(self) -> None:
        """刷新持仓数据并更新UI"""
        try:
            self.logger.debug("开始刷新持仓数据")

            # 先通过 UserDataManager 加载持仓数据到 app_core.position_data
            group_manager = getattr(self.app_core.app, 'group_manager', None)
            if group_manager:
                await group_manager.load_user_positions()
            else:
                self.logger.warning("UserDataManager 未初始化，无法刷新持仓数据")
                return

            # 然后委托给 UIManager 更新持仓显示UI
            ui_manager = getattr(self.app_core.app, 'ui_manager', None)
            if ui_manager:
                await ui_manager.update_position_display()
            else:
                self.logger.warning("UIManager 未初始化，跳过更新持仓显示UI")

            self.logger.debug(f"持仓数据刷新完成，共 {len(self.app_core.position_data)} 只持仓")

        except Exception as e:
            self.logger.error(f"刷新持仓数据失败: {e}")

    async def start_user_refresh(self) -> None:
        """启动用户数据定时刷新（订单和持仓，不依赖市场状态）"""
        try:
            # 检查是否已有用户数据刷新任务在运行
            if self.user_refresh_timer and not self.user_refresh_timer.done():
                self.logger.info("用户数据刷新任务已在运行，跳过重复启动")
                return

            # 取消现有任务（如果存在）
            if self.user_refresh_timer:
                self.user_refresh_timer.cancel()
                try:
                    await self.user_refresh_timer
                except asyncio.CancelledError:
                    pass

            # 立即执行一次用户数据刷新，避免等待第一个刷新周期
            self.logger.info("启动时立即加载订单和持仓数据")

            # 加载订单数据
            await self.refresh_order_data()

            # 加载持仓数据
            await self.refresh_position_data()

            # 创建定时刷新任务
            self.user_refresh_timer = asyncio.create_task(self.user_data_refresh_loop())
            self.logger.info(f"用户数据定时刷新启动，刷新间隔: {ORDER_REFRESH_INTERVAL}秒")

            # 向信息面板显示用户数据刷新启动信息
            if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                await self.app_core.app.ui_manager.info_panel.log_info("用户数据定时刷新已启动", "系统")

        except Exception as e:
            self.logger.error(f"启动用户数据定时刷新失败: {e}")

    async def user_data_refresh_loop(self) -> None:
        """用户数据定时刷新循环（订单和持仓）"""
        try:
            while True:
                try:
                    # 先等待刷新间隔，避免重复立即刷新
                    await asyncio.sleep(ORDER_REFRESH_INTERVAL)

                    # 刷新订单数据
                    await self.refresh_order_data()

                    # 刷新持仓数据
                    await self.refresh_position_data()

                    self.logger.debug(f"用户数据定时刷新完成，下次刷新: {ORDER_REFRESH_INTERVAL}秒后")

                except asyncio.CancelledError:
                    self.logger.info("用户数据定时刷新任务被取消")
                    break
                except Exception as e:
                    self.logger.error(f"用户数据定时刷新错误: {e}")
                    # 发生错误时等待一段时间再重试
                    await asyncio.sleep(ORDER_REFRESH_INTERVAL)

        except Exception as e:
            self.logger.error(f"用户数据刷新循环异常退出: {e}")

    async def stop_user_refresh(self) -> None:
        """停止用户数据定时刷新"""
        try:
            if self.user_refresh_timer:
                self.user_refresh_timer.cancel()
                try:
                    await self.user_refresh_timer
                except asyncio.CancelledError:
                    pass
                self.user_refresh_timer = None
                self.logger.info("用户数据定时刷新已停止")

                # 向信息面板显示用户数据刷新停止信息
                if hasattr(self.app_core, 'app') and hasattr(self.app_core.app, 'ui_manager') and self.app_core.app.ui_manager.info_panel:
                    await self.app_core.app.ui_manager.info_panel.log_info("用户数据定时刷新已停止", "系统")

        except Exception as e:
            self.logger.error(f"停止用户数据定时刷新失败: {e}")

    def cleanup_futu_market(self) -> None:
        """清理富途市场连接"""
        try:
            if hasattr(self.futu_market, 'close'):
                self.futu_market.close()
                self.logger.info("富途市场连接已清理")
        except Exception as e:
            self.logger.warning(f"清理富途市场连接时出错: {e}")
    
    def _load_basicinfo_cache_from_file(self) -> bool:
        """从本地文件加载股票基本信息缓存
        
        Returns:
            bool: 如果成功加载有效缓存返回True，否则返回False
        """
        try:
            cache_file_path = PATH_DATA / BASICINFO_CACHE_FILE
            
            if not cache_file_path.exists():
                self.logger.info("本地股票基本信息缓存文件不存在")
                return False

            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            if not isinstance(cache_data, dict) or not isinstance(cache_data.get('data'), dict):
                self.logger.warning("缓存文件格式无效")
                return False

            cached_basicinfo = cache_data['data']
            self.app_core.stock_basicinfo_cache.clear()
            self.app_core.stock_basicinfo_cache.update(cached_basicinfo)

            file_mtime = os.path.getmtime(cache_file_path)
            current_time = time.time()
            cache_age_hours = (current_time - file_mtime) / 3600
            if cache_age_hours > CACHE_EXPIRY_HOURS:
                self.logger.info(
                    f"股票基本信息缓存已过期 ({cache_age_hours:.1f}小时 > {CACHE_EXPIRY_HOURS}小时)，"
                    "已预载缓存数据，将从API刷新"
                )
                return False

            cached_stocks = set(cached_basicinfo.keys())
            monitored_stocks = set(self.app_core.monitored_stocks)

            if not monitored_stocks.issubset(cached_stocks):
                missing_stocks = monitored_stocks - cached_stocks
                self.logger.info(f"缓存中缺少部分股票信息: {missing_stocks}")
                return False

            self.logger.info(f"成功从本地缓存加载 {len(cached_basicinfo)} 只股票基本信息")
            return True
            
        except Exception as e:
            self.logger.error(f"加载本地股票基本信息缓存失败: {e}")
            return False
    
    def _save_basicinfo_cache_to_file(self) -> None:
        """将股票基本信息缓存保存到本地文件"""
        try:
            if not self.app_core.stock_basicinfo_cache:
                self.logger.warning("没有可保存的股票基本信息缓存")
                return
            
            os.makedirs(PATH_DATA, exist_ok=True)
            
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'cache_expiry_hours': CACHE_EXPIRY_HOURS,
                'data': self.app_core.stock_basicinfo_cache
            }
            
            cache_file_path = PATH_DATA / BASICINFO_CACHE_FILE
            
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"成功保存 {len(cache_data['data'])} 只股票基本信息到本地缓存")
            
        except Exception as e:
            self.logger.error(f"保存股票基本信息缓存失败: {e}")
    
    async def load_stock_basicinfo(self) -> None:
        """加载股票基本信息并缓存"""
        try:
            # 为监控的股票加载基本信息
            if not self.app_core.monitored_stocks:
                self.logger.info("没有监控的股票，跳过基本信息加载")
                return
            
            # 首先尝试从本地缓存加载
            if self._load_basicinfo_cache_from_file():
                self.logger.info("使用本地缓存的股票基本信息")
                return
            
            # 本地缓存无效，需要API连接来获取数据
            if self.app_core.connection_status != ConnectionStatus.CONNECTED:
                if self.app_core.stock_basicinfo_cache:
                    self.logger.warning("富途API未连接，继续使用已加载的股票基本信息缓存")
                else:
                    self.logger.warning("富途API未连接且本地缓存无效，无法加载股票基本信息")
                return
            
            self.logger.info(f"开始从API加载 {len(self.app_core.monitored_stocks)} 只股票的基本信息...")
            
            # 在线程池中执行同步的富途API调用
            loop = asyncio.get_event_loop()
            
            # 根据股票代码确定市场
            hk_stocks = [code for code in self.app_core.monitored_stocks if code.startswith('HK.')]
            us_stocks = [code for code in self.app_core.monitored_stocks if code.startswith('US.')]
            sh_stocks = [code for code in self.app_core.monitored_stocks if code.startswith('SH.')]
            sz_stocks = [code for code in self.app_core.monitored_stocks if code.startswith('SZ.')]
            
            # 分别获取不同市场的股票基本信息
            market_groups = [
                ("HK", hk_stocks),
                ("US", us_stocks),
                ("SH", sh_stocks),
                ("SZ", sz_stocks)
            ]
            
            total_loaded = 0
            for market, stocks in market_groups:
                if not stocks:
                    continue
                    
                try:
                    # 使用新的合并方法获取STOCK、IDX、ETF三种类型的证券信息
                    basicinfo_list = await loop.run_in_executor(
                        None,
                        self.futu_market.get_stock_basicinfo_multi_types,
                        market,
                        ["STOCK", "IDX", "ETF"]
                    )
                    
                    if basicinfo_list:
                        for basicinfo in basicinfo_list:
                            if hasattr(basicinfo, 'code'):
                                stock_code = basicinfo.code
                                # 缓存所有获取到的证券信息
                                self.app_core.stock_basicinfo_cache[stock_code] = {
                                    'code': basicinfo.code,
                                    'name': getattr(basicinfo, 'name', ''),
                                    'lot_size': getattr(basicinfo, 'lot_size', 0),
                                    'stock_type': getattr(basicinfo, 'stock_type', ''),
                                    'main_contract': getattr(basicinfo, 'main_contract', False),
                                    'stock_child_type': getattr(basicinfo, 'stock_child_type', ''),
                                    'listing_date': getattr(basicinfo, 'listing_date', None),
                                    'delisting_date': getattr(basicinfo, 'delisting_date', None),
                                    'last_update': datetime.now().isoformat()
                                }
                                total_loaded += 1
                            elif isinstance(basicinfo, dict):
                                stock_code = basicinfo.get('code', '')
                                if stock_code:
                                    # 缓存所有获取到的证券信息
                                    self.app_core.stock_basicinfo_cache[stock_code] = {
                                        'code': stock_code,
                                        'name': basicinfo.get('name', ''),
                                        'lot_size': basicinfo.get('lot_size', 0),
                                        'stock_type': basicinfo.get('stock_type', ''),
                                        'main_contract': basicinfo.get('main_contract', False),
                                        'stock_child_type': basicinfo.get('stock_child_type', ''),
                                        'listing_date': basicinfo.get('listing_date', None),
                                        'delisting_date': basicinfo.get('delisting_date', None),
                                        'last_update': datetime.now().isoformat()
                                    }
                                    total_loaded += 1
                    
                    self.logger.info(f"加载 {market} 市场证券基本信息完成，共缓存 {len(basicinfo_list) if basicinfo_list else 0} 只证券（支持STOCK/IDX/ETF类型）")
                    
                except Exception as e:
                    self.logger.error(f"加载 {market} 市场股票基本信息失败: {e}")
                    continue
            
            if total_loaded > 0:
                # API调用成功，保存到本地缓存
                self._save_basicinfo_cache_to_file()
                self.logger.info(f"股票基本信息加载完成，共缓存 {total_loaded} 只股票并保存到本地")
            else:
                self.logger.warning("未能从API获取到任何股票基本信息")
            
        except Exception as e:
            self.logger.error(f"加载股票基本信息失败: {e}")
    
    async def refresh_stock_basicinfo(self) -> None:
        """刷新股票基本信息缓存"""
        try:
            self.logger.info("开始刷新股票基本信息缓存...")
            
            # 清空现有缓存
            self.app_core.stock_basicinfo_cache.clear()
            
            # 重新加载基本信息
            await self.load_stock_basicinfo()
            
            self.logger.info("股票基本信息缓存刷新完成")
            
        except Exception as e:
            self.logger.error(f"刷新股票基本信息缓存失败: {e}")
    
    def get_stock_basicinfo_from_cache(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """从缓存中获取股票基本信息"""
        try:
            return self.app_core.stock_basicinfo_cache.get(stock_code)
        except Exception as e:
            self.logger.error(f"从缓存获取股票基本信息失败: {e}")
            return None
    
    def get_stock_code_from_cache_full(self):
        try:
            return [ x for x in self.app_core.stock_basicinfo_cache.keys()]
        except Exception as e:
            self.logger.error(f"从缓存获取股票基本信息失败: {e}")
            return None
