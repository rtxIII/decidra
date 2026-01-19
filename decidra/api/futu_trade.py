"""
富途交易管理器模块

负责处理所有交易相关的API调用，包括账户信息查询、
下单、撤单、持仓查询等功能。
"""

import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from ..utils.global_vars import get_logger
import pandas as pd
if TYPE_CHECKING:
    from .futu_client import FutuClient

from ..base.futu_class import FutuException, FutuTradeException

try:
    import futu as ft
except ImportError:
    raise ImportError(
        "futu-api is required. Install it with: pip install futu-api"
    )


class TradeManager:
    """富途交易管理器"""
    
    def __init__(self, client: 'FutuClient'):
        """
        初始化交易管理器
        
        Args:
            client: 富途客户端实例
        """
        self.client = client
        #self.logger = logging.getLogger(f"{__name__}.TradeManager")
        self.logger = get_logger(__name__)
    
    def _get_trade_context(self, market: str = "HK"):
        """获取交易上下文"""
        return self.client._get_trade_context(market)
    
    def _handle_response(self, ret_code: int, ret_data: Any, operation: str = "操作"):
        """处理富途API响应"""
        if ret_code != ft.RET_OK:
            error_msg = f"{operation}失败: {ret_data}"
            self.logger.error(error_msg)
            raise FutuTradeException(ret_code, ret_data)
        
        # 处理DataFrame格式数据
        try:
            import pandas as pd
            if isinstance(ret_data, pd.DataFrame):
                # 处理DataFrame中的特殊数据类型
                if not ret_data.empty:
                    # 替换NaN值为None
                    ret_data = ret_data.where(pd.notnull(ret_data), None)
                    # 确保数据类型兼容性
                    for col in ret_data.columns:
                        if ret_data[col].dtype == 'object':
                            # 将字符串'nan'和'None'转换为None
                            ret_data[col] = ret_data[col].astype(str)
                            ret_data[col] = ret_data[col].replace(['nan', 'None', '<NA>'], None)
                
                # 转换为字典格式以确保兼容性
                if len(ret_data) == 1:
                    # 单行数据返回字典
                    return ret_data.iloc[0].to_dict()
                else:
                    # 多行数据返回DataFrame
                    return ret_data
            else:
                # 非DataFrame数据直接返回
                return ret_data
        except ImportError:
            # 如果pandas不可用，直接返回原数据
            return ret_data
        except Exception as e:
            self.logger.warning(f"数据格式处理异常: {e}，返回原始数据")
            return ret_data
    
    def get_acc_list(self, market: str = "HK") -> List[Dict]:
        """
        获取账户列表

        Args:
            market: 市场代码 (HK/US/CN)

        Returns:
            Dict: 账户列表信息
        """
        try:
            trade_ctx = self._get_trade_context(market)

            ret, data = trade_ctx.get_acc_list()

            # 直接检查返回状态，不使用_handle_response（因为它会处理多行数据）
            if ret != ft.RET_OK:
                error_msg = f"获取账户列表失败: {data}"
                self.logger.error(error_msg)
                raise FutuTradeException(ret, data)

            # 对于账户列表，我们需要返回完整的DataFrame数据
            if isinstance(data, pd.DataFrame) and not data.empty:
                self.logger.debug(f"获取账户列表成功，共 {len(data)} 个账户")
                return data.to_dict('records')  # 转换为字典列表
            else:
                self.logger.warning("获取账户列表返回空数据")
                return []

        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取账户列表异常: {str(e)}")
    
    def unlock_trade(self, password: str = None, password_md5: str = None, market: str = "HK"):
        """
        解锁交易

        Args:
            password: 交易密码（明文）
            password_md5: 交易密码（MD5加密后）
            market: 市场代码

        Returns:
            bool: 解锁结果
        """
        try:
            trade_ctx = self._get_trade_context(market)

            ret, data = trade_ctx.unlock_trade(password=password, password_md5=password_md5, is_unlock=True)
            
            if ret == 0:         
                self.logger.w("交易解锁成功")
                return True
            else:
                self.logger.error(f"交易解锁失败: {data}")
                return False
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"解锁交易异常: {str(e)}")
    
    def get_cash_flow(self,
                     trd_env: str = "SIMULATE",
                     market: str = "HK",
                     start: Optional[str] = None,
                     end: Optional[str] = None,
                     currency: str = "HKD") -> Dict:
        """
        获取现金流水

        Args:
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)
            currency: 货币类型 (注意: API不直接支持货币过滤)

        Returns:
            Dict: 现金流水信息
        """
        try:
            trade_ctx = self._get_trade_context(market)

            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE

            # 注意: get_acc_cash_flow 不需要currency参数，现金流水会显示各种货币
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {trd_env} 环境现金流水")

            # get_acc_cash_flow只支持单日查询，需要按日期逐一查询
            # 富途API要求日期格式为 "yyyy-MM-dd"，例如："2017-06-20"

            def validate_date_format(date_str):
                """验证并标准化日期格式"""
                if not date_str:
                    return ""
                try:
                    # 尝试解析日期并重新格式化确保格式正确
                    import datetime as dt
                    parsed_date = dt.datetime.strptime(date_str, "%Y-%m-%d")
                    return parsed_date.strftime("%Y-%m-%d")
                except ValueError as e:
                    self.logger.error(f"日期格式错误: {date_str}, 需要格式: YYYY-MM-DD, 错误: {e}")
                    return None

            if start and end:
                # 验证日期格式
                validated_start = validate_date_format(start)
                validated_end = validate_date_format(end)

                if not validated_start or not validated_end:
                    return []

                # 如果指定了日期范围，需要逐日查询并合并结果
                import datetime as dt
                from datetime import timedelta

                all_data = []
                current_date = dt.datetime.strptime(validated_start, "%Y-%m-%d")
                end_date = dt.datetime.strptime(validated_end, "%Y-%m-%d")

                self.logger.debug(f"查询日期范围: {validated_start} 到 {validated_end}")

                while current_date <= end_date:
                    date_str = current_date.strftime("%Y-%m-%d")

                    self.logger.debug(f"查询日期: {date_str}")

                    ret, data = trade_ctx.get_acc_cash_flow(
                        clearing_date=date_str,
                        trd_env=futu_env,
                        acc_id=acc_id,
                        acc_index=0
                    )

                    if ret == ft.RET_OK and isinstance(data, pd.DataFrame) and not data.empty:
                        all_data.append(data)
                        self.logger.debug(f"找到 {date_str} 的现金流水 {len(data)} 条记录")
                    elif ret != ft.RET_OK:
                        self.logger.warning(f"查询日期 {date_str} 失败: {data}")

                    current_date += timedelta(days=1)

                # 合并所有日期的数据
                if all_data:
                    combined_data = pd.concat(all_data, ignore_index=True)
                    df = self._handle_response(ft.RET_OK, combined_data, "获取现金流水")
                else:
                    self.logger.warning(f"未找到 {validated_start} 到 {validated_end} 期间的现金流水数据")
                    return []
            else:
                # 单日查询或查询今日
                if start:
                    validated_date = validate_date_format(start)
                    if not validated_date:
                        return []
                    clearing_date = validated_date
                    self.logger.debug(f"查询单日现金流水: {clearing_date}")
                else:
                    # 查询今日，需要传入今天的日期
                    import datetime as dt
                    today = dt.datetime.now().strftime("%Y-%m-%d")
                    clearing_date = today
                    self.logger.debug(f"查询今日现金流水: {clearing_date}")

                ret, data = trade_ctx.get_acc_cash_flow(
                    clearing_date=clearing_date,
                    trd_env=futu_env,
                    acc_id=acc_id,
                    acc_index=0
                )

                df = self._handle_response(ret, data, "获取现金流水")
            
            self.logger.info(f"获取 {trd_env} 环境现金流水成功")
            return df
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取现金流水异常: {str(e)}")
    
    def _get_active_account_id(self, trd_env: str, market: str) -> int:
        """
        获取指定交易环境下的可用账户ID

        Args:
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码

        Returns:
            int: 可用的账户ID，如果没有找到则返回0（使用默认）
        """
        try:
            # 获取账户列表
            acc_list = self.get_acc_list(market)

            if not acc_list:
                self.logger.warning(f"未找到 {market} 市场的账户列表")
                return 0

            # 筛选指定环境和状态为ACTIVE的账户
            for acc in acc_list:
                if (acc.get('trd_env') == trd_env.upper() and
                    acc.get('acc_status') == 'ACTIVE'):
                    acc_id = acc.get('acc_id')
                    self.logger.info(f"找到可用的{trd_env}账户: {acc_id}")
                    return int(acc_id)

            # 如果没有找到ACTIVE账户，尝试使用任何可用的账户（状态不是DISABLED）
            for acc in acc_list:
                if (acc.get('trd_env') == trd_env.upper() and
                    acc.get('acc_status') != 'DISABLED'):
                    acc_id = acc.get('acc_id')
                    self.logger.warning(f"使用非ACTIVE状态的{trd_env}账户: {acc_id}, 状态: {acc.get('acc_status')}")
                    return int(acc_id)

            self.logger.error(f"未找到可用的{trd_env}账户")
            return 0

        except Exception as e:
            self.logger.error(f"获取可用账户ID失败: {e}")
            return 0

    def get_funds(self,
                  trd_env: str = "SIMULATE",
                  market: str = "HK",
                  currency: str = "HKD") -> Dict:
        """
        获取账户资金信息

        Args:
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码
            currency: 货币类型

        Returns:
            Dict: 资金信息
        """
        try:
            trade_ctx = self._get_trade_context(market)

            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE

            # 转换货币类型
            currency_map = {
                "HKD": ft.Currency.HKD,
                "USD": ft.Currency.USD
                # CNY is not supported in this version of futu-api
            }
            futu_currency = currency_map.get(currency.upper(), ft.Currency.HKD)

            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {trd_env} 环境资金信息")

            ret, data = trade_ctx.accinfo_query(
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0,
                currency=futu_currency,
                refresh_cache=False
            )

            df = self._handle_response(ret, data, "获取账户资金")

            self.logger.info(f"获取 {trd_env} 环境账户资金成功")
            return df

        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取账户资金异常: {str(e)}")
    
    def get_account_info(self, trd_env: str = "SIMULATE", market: str = "HK", currency: str = "HKD") -> Dict:
        """
        获取账户信息
        
        Args:
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码
            currency: 货币类型
        
        Returns:
            Dict: 账户信息
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 转换货币类型
            currency_map = {
                "HKD": ft.Currency.HKD,
                "USD": ft.Currency.USD
                # CNY is not supported in this version of futu-api
            }
            futu_currency = currency_map.get(currency.upper(), ft.Currency.HKD)
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {trd_env} 环境账户信息")

            ret, data = trade_ctx.accinfo_query(
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0,
                refresh_cache=False,
                currency=futu_currency
            )
            
            df = self._handle_response(ret, data, "获取账户信息")

            self.logger.info(f"获取 {trd_env} 环境账户信息成功")
            return df
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取账户信息异常: {str(e)}")
    
    def get_position_list(self,
                         trd_env: str = "SIMULATE",
                         market: str = "HK",
                         code: Optional[str] = None,
                         pl_ratio_min: Optional[float] = None,
                         pl_ratio_max: Optional[float] = None,
                         currency: str = "HKD") -> Dict:
        """
        获取持仓列表

        Args:
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码 (HK/US/CN)
            code: 股票代码，为None则获取所有持仓
            pl_ratio_min: 盈亏比例下限
            pl_ratio_max: 盈亏比例上限
            currency: 货币类型 (注意: API不支持货币过滤，返回所有货币持仓)

        Returns:
            Dict: 持仓信息
        """
        try:
            trade_ctx = self._get_trade_context(market)

            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE

            # 注意: position_list_query 不支持currency参数，持仓数据会显示各种货币
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {trd_env} 环境持仓列表")

            ret, data = trade_ctx.position_list_query(
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0,
                code=code,
                pl_ratio_min=pl_ratio_min,
                pl_ratio_max=pl_ratio_max,
                refresh_cache=False
            )
            #print(data)
            df = self._handle_response(ret, data, "获取持仓列表")
            
            self.logger.debug(f"获取 {trd_env} 环境持仓列表成功")
            return df
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取持仓列表异常: {str(e)}")
    
    def place_order(self,
                   code: str,
                   price: float,
                   qty: int,
                   order_type: str = "NORMAL",
                   trd_side: str = "BUY",
                   aux_price: Optional[float] = None,
                   trd_env: str = "SIMULATE",
                   market: str = "HK") -> Dict:
        """
        下单

        Args:
            code: 股票代码 (如 "HK.00700")
            price: 下单价格
            qty: 下单数量
            order_type: 订单类型
                - NORMAL: 限价单
                - MARKET: 市价单
                - STOP: 止损单
                - STOP_LIMIT: 止损限价单
                - TRAILING_STOP: 触及市价单(止盈)
                - TRAILING_STOP_LIMIT: 触及限价单(止盈)
                - ABSOLUTE_LIMIT: 绝对限价单
                - AUCTION: 竞价单
                - AUCTION_LIMIT: 竞价限价单
                - SPECIAL_LIMIT: 特别限价单
            trd_side: 交易方向 (BUY-买入, SELL-卖出)
            aux_price: 辅助价格，用于止损止盈订单的触发价格
            trd_env: 交易环境 (REAL/SIMULATE)
            market: 市场代码

        Returns:
            Dict: 下单结果
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                futu_order_type = ft.OrderType.MARKET
            elif order_type.upper() == "STOP":
                futu_order_type = ft.OrderType.STOP
            elif order_type.upper() == "STOP_LIMIT":
                futu_order_type = ft.OrderType.STOP_LIMIT
            elif order_type.upper() == "TRAILING_STOP":
                futu_order_type = ft.OrderType.TRAILING_STOP
            elif order_type.upper() == "TRAILING_STOP_LIMIT":
                futu_order_type = ft.OrderType.TRAILING_STOP_LIMIT
            elif order_type.upper() == "ABSOLUTE_LIMIT":
                futu_order_type = ft.OrderType.ABSOLUTE_LIMIT
            elif order_type.upper() == "AUCTION":
                futu_order_type = ft.OrderType.AUCTION
            elif order_type.upper() == "AUCTION_LIMIT":
                futu_order_type = ft.OrderType.AUCTION_LIMIT
            elif order_type.upper() == "SPECIAL_LIMIT":
                futu_order_type = ft.OrderType.SPECIAL_LIMIT
            else:
                futu_order_type = ft.OrderType.NORMAL
            
            # 转换交易方向
            futu_trd_side = ft.TrdSide.BUY if trd_side.upper() == "BUY" else ft.TrdSide.SELL
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 在 {trd_env} 环境下单: {code} {trd_side} {qty}@{price}")

            ret, data = trade_ctx.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=futu_trd_side,
                order_type=futu_order_type,
                aux_price=aux_price,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            result = self._handle_response(ret, data, f"下单 {code}")
            
            self.logger.info(f"下单成功: {code} {trd_side} {qty}@{price}")
            return result
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"下单异常: {str(e)}")
    
    def modify_order(self,
                    order_id: str,
                    price: Optional[float] = None,
                    qty: Optional[int] = None,
                    trd_env: str = "SIMULATE",
                    market: str = "HK") -> Dict:
        """
        修改订单
        
        Args:
            order_id: 订单ID
            price: 新价格，为None则不修改
            qty: 新数量，为None则不修改
            trd_env: 交易环境
            market: 市场代码
        
        Returns:
            Dict: 修改结果
        """
        try:
            # 参数验证
            if price is None and qty is None:
                raise FutuTradeException(-1, "修改订单至少需要指定价格或数量中的一个")

            trade_ctx = self._get_trade_context(market)

            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE

            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 在 {trd_env} 环境修改订单: {order_id}")

            # 如果只指定了其中一个参数，需要先获取原订单信息
            if price is None or qty is None:
                # 获取原订单信息以补全缺失参数
                order_list = trade_ctx.order_list_query(
                    order_id=order_id,
                    trd_env=futu_env,
                    acc_id=acc_id,
                    acc_index=0
                )[1]

                if order_list.empty:
                    raise FutuTradeException(-1, f"找不到订单 {order_id}")

                original_order = order_list.iloc[0]
                price = price if price is not None else float(original_order['price'])
                qty = qty if qty is not None else int(original_order['qty'])

            ret, data = trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.NORMAL,
                order_id=order_id,
                price=price,
                qty=qty,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            result = self._handle_response(ret, data, f"修改订单 {order_id}")
            
            self.logger.info(f"修改订单成功: {order_id}")
            return result
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"修改订单异常: {str(e)}")
    
    def cancel_order(self,
                    order_id: str,
                    trd_env: str = "SIMULATE",
                    market: str = "HK") -> Dict:
        """
        撤销订单
        
        Args:
            order_id: 订单ID
            trd_env: 交易环境
            market: 市场代码
        
        Returns:
            Dict: 撤销结果
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 在 {trd_env} 环境撤销订单: {order_id}")

            ret, data = trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.CANCEL,
                order_id=order_id,
                price=0,  # 撤销订单时价格和数量参数必需但不会被使用
                qty=0,    # 撤销订单时价格和数量参数必需但不会被使用
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            result = self._handle_response(ret, data, f"撤销订单 {order_id}")
            
            self.logger.info(f"撤销订单成功: {order_id}")
            return result
            
        except Exception as e:
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"撤销订单异常: {str(e)}")
    
    def get_order_list(self,
                      order_status: Optional[str] = None,
                      trd_env: str = "SIMULATE",
                      market: str = "HK",
                      start: Optional[str] = None,
                      end: Optional[str] = None) -> Dict:
        """
        获取订单列表
        
        Args:
            order_status: 订单状态过滤 (UNSUBMITTED/WAITING_SUBMIT/SUBMITTING/SUBMITTED等)
            trd_env: 交易环境
            market: 市场代码
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)
        
        Returns:
            Dict: 订单列表
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 转换订单状态
            futu_status_filter_list = []
            if order_status:
                status_map = {
                    "UNSUBMITTED": ft.OrderStatus.UNSUBMITTED,
                    "WAITING_SUBMIT": ft.OrderStatus.WAITING_SUBMIT,
                    "SUBMITTING": ft.OrderStatus.SUBMITTING,
                    "SUBMITTED": ft.OrderStatus.SUBMITTED,
                    "FILLED_PART": ft.OrderStatus.FILLED_PART,
                    "FILLED_ALL": ft.OrderStatus.FILLED_ALL,
                    "CANCELLED_PART": ft.OrderStatus.CANCELLED_PART,
                    "CANCELLED_ALL": ft.OrderStatus.CANCELLED_ALL,
                    "FAILED": ft.OrderStatus.FAILED,
                    "DISABLED": ft.OrderStatus.DISABLED,
                    "DELETED": ft.OrderStatus.DELETED
                }
                if order_status.upper() in status_map:
                    futu_status_filter_list = [status_map[order_status.upper()]]
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            ret, data = trade_ctx.order_list_query(
                order_id="",
                status_filter_list=futu_status_filter_list,
                code="",
                start=start,
                end=end,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0,
                refresh_cache=False
            )
            
            df = self._handle_response(ret, data, "获取订单列表")
            
            return df
            
        except Exception as e:
            self.logger.error(f"获取订单列表异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取订单列表异常: {str(e)}")
    
    def get_deal_list(self,
                     trd_env: str = "SIMULATE",
                     market: str = "HK") -> Dict:
        """
        获取成交列表

        Args:
            trd_env: 交易环境
            market: 市场代码

        Returns:
            Dict: 成交列表
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.info(f"使用账户ID {acc_id} 查询 {trd_env} 环境成交列表")

            ret, data = trade_ctx.deal_list_query(
                code="",
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0,
                refresh_cache=False
            )
            
            df = self._handle_response(ret, data, "获取成交列表")
            
            self.logger.debug(f"获取 {trd_env} 环境成交列表成功")
            return df
            
        except Exception as e:
            self.logger.error(f"获取成交列表异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取成交列表异常: {str(e)}")
    
    def get_history_order_list(self,
                              trd_env: str = "SIMULATE",
                              market: str = "HK",
                              start: Optional[str] = None,
                              end: Optional[str] = None) -> Dict:
        """
        获取历史订单列表
        
        Args:
            trd_env: 交易环境
            market: 市场代码
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)
        
        Returns:
            Dict: 历史订单列表
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.info(f"使用账户ID {acc_id} 查询 {trd_env} 环境历史订单列表")

            ret, data = trade_ctx.history_order_list_query(
                status_filter_list=[],
                code="",
                start=start,
                end=end,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            df = self._handle_response(ret, data, "获取历史订单列表")
            
            self.logger.debug(f"获取 {trd_env} 环境历史订单列表成功")
            return df
            
        except Exception as e:
            self.logger.error(f"获取历史订单列表异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取历史订单列表异常: {str(e)}")
    
    def get_history_deal_list(self,
                             trd_env: str = "SIMULATE",
                             market: str = "HK",
                             start: Optional[str] = None,
                             end: Optional[str] = None) -> Dict:
        """
        获取历史成交列表
        
        Args:
            trd_env: 交易环境
            market: 市场代码
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)
        
        Returns:
            Dict: 历史成交列表
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {trd_env} 环境历史成交列表")

            ret, data = trade_ctx.history_deal_list_query(
                code="",
                start=start,
                end=end,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            df = self._handle_response(ret, data, "获取历史成交列表")
            
            self.logger.debug(f"获取 {trd_env} 环境历史成交列表成功")
            return df
            
        except Exception as e:
            self.logger.error(f"获取历史成交列表异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取历史成交列表异常: {str(e)}")
    
    def get_max_trd_qty(self,
                       order_type: str,
                       code: str,
                       price: float,
                       trd_side: str = "BUY",
                       trd_env: str = "SIMULATE",
                       market: str = "HK") -> Dict:
        """
        获取最大交易数量
        
        Args:
            order_type: 订单类型 (NORMAL/MARKET等)
            code: 股票代码
            price: 价格
            trd_side: 交易方向 (BUY/SELL)
            trd_env: 交易环境
            market: 市场代码
        
        Returns:
            Dict: 最大交易数量信息
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                futu_order_type = ft.OrderType.MARKET
            else:
                futu_order_type = ft.OrderType.NORMAL
            
            # 转换交易方向
            futu_trd_side = ft.TrdSide.BUY if trd_side.upper() == "BUY" else ft.TrdSide.SELL
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {code} 最大交易数量")

            ret, data = trade_ctx.acctradinginfo_query(
                order_type=futu_order_type,
                code=code,
                price=price,
                trd_side=futu_trd_side,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            df = self._handle_response(ret, data, f"获取 {code} 最大交易数量")
            
            self.logger.debug(f"获取 {code} 最大交易数量成功")
            return df
            
        except Exception as e:
            self.logger.error(f"获取最大交易数量异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取最大交易数量异常: {str(e)}")
    
    def get_order_fee(self,
                     order_type: str,
                     code: str,
                     price: float,
                     qty: int,
                     trd_side: str = "BUY",
                     trd_env: str = "SIMULATE",
                     market: str = "HK") -> Dict:
        """
        获取订单费用预估
        
        Args:
            order_type: 订单类型
            code: 股票代码
            price: 价格
            qty: 数量
            trd_side: 交易方向
            trd_env: 交易环境
            market: 市场代码
        
        Returns:
            Dict: 费用预估信息
        """
        try:
            trade_ctx = self._get_trade_context(market)
            
            # 转换交易环境
            futu_env = ft.TrdEnv.REAL if trd_env.upper() == "REAL" else ft.TrdEnv.SIMULATE
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                futu_order_type = ft.OrderType.MARKET
            else:
                futu_order_type = ft.OrderType.NORMAL
            
            # 转换交易方向
            futu_trd_side = ft.TrdSide.BUY if trd_side.upper() == "BUY" else ft.TrdSide.SELL
            
            # 动态获取可用的账户ID
            acc_id = self._get_active_account_id(trd_env, market)

            self.logger.debug(f"使用账户ID {acc_id} 查询 {code} 订单费用")

            ret, data = trade_ctx.order_fee_query(
                order_type=futu_order_type,
                code=code,
                price=price,
                qty=qty,
                trd_side=futu_trd_side,
                trd_env=futu_env,
                acc_id=acc_id,
                acc_index=0
            )
            
            df = self._handle_response(ret, data, f"获取 {code} 订单费用")
            
            self.logger.debug(f"获取 {code} 订单费用成功")
            return df
            
        except Exception as e:
            self.logger.error(f"获取订单费用异常: {str(e)}")
            if isinstance(e, FutuException):
                raise
            raise FutuTradeException(-1, f"获取订单费用异常: {str(e)}")
    
    def set_order_callback(self, callback_func, market: str = "HK"):
        """
        设置订单推送回调
        
        Args:
            callback_func: 回调函数
            market: 市场代码
        """
        try:
            trade_ctx = self._get_trade_context(market)
            trade_ctx.set_handler(ft.OrderStatus, callback_func)
            self.logger.debug("订单推送回调设置成功")
            
        except Exception as e:
            self.logger.error(f"设置订单推送回调异常: {str(e)}")
            raise FutuTradeException(-1, f"设置订单推送回调异常: {str(e)}")
    
    def set_deal_callback(self, callback_func, market: str = "HK"):
        """
        设置成交推送回调
        
        Args:
            callback_func: 回调函数
            market: 市场代码
        """
        try:
            trade_ctx = self._get_trade_context(market)
            trade_ctx.set_handler(ft.DealStatus, callback_func)
            self.logger.debug("成交推送回调设置成功")
            
        except Exception as e:
            self.logger.error(f"设置成交推送回调异常: {str(e)}")
            raise FutuTradeException(-1, f"设置成交推送回调异常: {str(e)}")
    
    def enable_subscribe_order(self, market: str = "HK"):
        """
        启用订单推送订阅
        
        Args:
            market: 市场代码
        """
        try:
            trade_ctx = self._get_trade_context(market)
            ret, data = trade_ctx.subscribe(subtype_list=[ft.SubType.ORDER])
            self._handle_response(ret, data, "订单推送订阅")
            self.logger.debug("订单推送订阅启用成功")
            
        except Exception as e:
            self.logger.error(f"启用订单推送订阅异常: {str(e)}")
            raise FutuTradeException(-1, f"启用订单推送订阅异常: {str(e)}")
    
    def enable_subscribe_deal(self, market: str = "HK"):
        """
        启用成交推送订阅
        
        Args:
            market: 市场代码
        """
        try:
            trade_ctx = self._get_trade_context(market)
            ret, data = trade_ctx.subscribe(subtype_list=[ft.SubType.DEAL])
            self._handle_response(ret, data, "成交推送订阅")
            self.logger.debug("成交推送订阅启用成功")
            
        except Exception as e:
            self.logger.error(f"启用成交推送订阅异常: {str(e)}")
            raise FutuTradeException(-1, f"启用成交推送订阅异常: {str(e)}")