"""富途行情/交易 MCP 服务器（stdio）。

以 MCP 工具形式暴露 Decidra 的富途能力，供终端 agent 调用。复用现有
``FutuMarket`` / ``FutuTrade`` 封装（相同市场/trd_env 约定与风控），不重写富途逻辑。

工具分三层：
- 行情（只读）：quote / snapshot / kline / orderbook / capital_flow / broker_queue
- 账户（只读）：positions / funds / order_list / deal_list
- 交易（受控写）：place_order（默认模拟盘、启用风控；agent 侧经终端权限对话框二次确认）

富途实例延迟创建（首次调用工具时才连 OpenD），使服务器在 OpenD 未启动时仍可启动，
仅在调用具体工具时才报错。
"""

from __future__ import annotations

import concurrent.futures
import json
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

# 富途 SDK 为同步阻塞调用；OpenD 未授权行情/配额不足时会长时间阻塞。用线程 + 超时
# 包装，使工具超时返回错误而非挂死 agent 回合。
TOOL_TIMEOUT_SECONDS: float = 15.0
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="futu-tool")

_market: Any = None
_trade: Any = None


def _get_market():
    """延迟获取 FutuMarket 单例（首次调用时连接 OpenD）。"""
    global _market
    if _market is None:
        from decidra.modules.futu_market import FutuMarket
        _market = FutuMarket()
    return _market


def _get_trade():
    """延迟获取 FutuTrade 单例（首次调用时连接 OpenD）。"""
    global _trade
    if _trade is None:
        from decidra.modules.futu_trade import FutuTrade
        _trade = FutuTrade(default_trd_env="SIMULATE")
    return _trade


def _serialize(obj: Any) -> Any:
    """把富途返回值转为 JSON 可序列化结构（DataFrame/对象/嵌套）。"""
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
    except Exception:
        pass
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "to_dict"):
        try:
            return _serialize(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {str(k): _serialize(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _ok(data: Any) -> str:
    """成功结果 → JSON 字符串。"""
    return json.dumps({"ok": True, "data": _serialize(data)}, ensure_ascii=False, default=str)


def _err(message: str) -> str:
    """错误结果 → JSON 字符串。"""
    return json.dumps({"ok": False, "error": str(message)}, ensure_ascii=False)


def _guarded(call: Callable[[], Any]) -> str:
    """在超时保护下执行富途调用，返回 JSON 字符串。

    Args:
        call: 无参可调用，内部执行阻塞式富途请求。

    Returns:
        成功为 ``_ok(结果)``，超时或异常为 ``_err(...)``。
    """
    try:
        future = _EXECUTOR.submit(call)
        return _ok(future.result(timeout=TOOL_TIMEOUT_SECONDS))
    except concurrent.futures.TimeoutError:
        return _err(f"富途请求超时（>{TOOL_TIMEOUT_SECONDS:.0f}s），请确认 OpenD 已连接且账户具备行情权限")
    except Exception as exc:
        return _err(exc)


def build_server() -> FastMCP:
    """构建富途 MCP 服务器并注册所有工具。"""
    mcp = FastMCP("futu")

    # ——————————————— 行情（只读） ———————————————

    @mcp.tool()
    def futu_get_quote(codes: list[str]) -> str:
        """获取一只或多只股票的实时报价。

        Args:
            codes: 股票代码列表，格式如 ["HK.00700", "US.AAPL", "SH.600000"]。
        """
        return _guarded(lambda: _get_market().get_stock_quote(codes))

    @mcp.tool()
    def futu_get_snapshot(codes: list[str]) -> str:
        """获取股票市场快照（含最新价、涨跌幅、成交量、换手率等）。

        Args:
            codes: 股票代码列表，如 ["HK.00700"]。
        """
        return _guarded(lambda: _get_market().get_market_snapshot(codes))

    @mcp.tool()
    def futu_get_kline(code: str, num: int = 100, ktype: str = "K_DAY", autype: str = "qfq") -> str:
        """获取股票 K 线数据。

        Args:
            code: 股票代码，如 "HK.00700"。
            num: K 线数量，默认 100。
            ktype: K 线类型，如 K_DAY / K_WEEK / K_MON / K_1M / K_5M / K_15M / K_60M。
            autype: 复权类型，qfq（前复权）/ hfq（后复权）/ None（不复权）。
        """
        return _guarded(lambda: _get_market().get_cur_kline([code], num=num, ktype=ktype, autype=autype))

    @mcp.tool()
    def futu_get_orderbook(code: str) -> str:
        """获取股票的买卖盘口（五档/十档）。

        Args:
            code: 股票代码，如 "HK.00700"。
        """
        return _guarded(lambda: _get_market().get_order_book(code))

    @mcp.tool()
    def futu_get_broker_queue(code: str) -> str:
        """获取股票的经纪队列（买卖经纪商排队）。

        Args:
            code: 股票代码，如 "HK.00700"。
        """
        return _guarded(lambda: _get_market().get_broker_queue(code))

    # ——————————————— 账户（只读） ———————————————

    @mcp.tool()
    def futu_get_positions(trd_env: str = "SIMULATE", market: str = "HK") -> str:
        """获取当前持仓列表。

        Args:
            trd_env: 交易环境，SIMULATE（模拟盘）或 REAL（实盘），默认 SIMULATE。
            market: 市场，HK / US / CN，默认 HK。
        """
        return _guarded(lambda: _get_trade().get_position_list(trd_env=trd_env, market=market))

    @mcp.tool()
    def futu_get_funds(trd_env: str = "SIMULATE", market: str = "HK") -> str:
        """获取账户资金信息（总资产、现金、市值、可用资金等）。

        Args:
            trd_env: 交易环境，SIMULATE 或 REAL，默认 SIMULATE。
            market: 市场，HK / US / CN，默认 HK。
        """
        return _guarded(lambda: _get_trade().get_funds_info(trd_env=trd_env, market=market))

    @mcp.tool()
    def futu_get_order_list(order_status: str | None = None, trd_env: str = "SIMULATE", market: str = "HK") -> str:
        """获取订单列表。

        Args:
            order_status: 订单状态过滤，如 SUBMITTED / FILLED_ALL / CANCELLED_ALL；None 为全部。
            trd_env: 交易环境，SIMULATE 或 REAL，默认 SIMULATE。
            market: 市场，HK / US / CN，默认 HK。
        """
        return _guarded(lambda: _get_trade().get_order_list(order_status=order_status, trd_env=trd_env, market=market))

    @mcp.tool()
    def futu_get_deal_list(trd_env: str = "SIMULATE", market: str = "HK") -> str:
        """获取当日成交记录列表。

        Args:
            trd_env: 交易环境，SIMULATE 或 REAL，默认 SIMULATE。
            market: 市场，HK / US / CN，默认 HK。
        """
        return _guarded(lambda: _get_trade().get_deal_list(trd_env=trd_env, market=market))

    # ——————————————— 交易（受控写） ———————————————

    @mcp.tool()
    def futu_place_order(
        code: str,
        price: float,
        qty: int,
        trd_side: str = "BUY",
        order_type: str = "NORMAL",
        trd_env: str = "SIMULATE",
        market: str = "HK",
    ) -> str:
        """下单（买入/卖出）。这是会真实成交的操作，请谨慎。

        默认在模拟盘（SIMULATE）执行并启用风控检查。实盘（REAL）下单前需先解锁交易，
        且涉及真实资金——只有在用户明确要求实盘时才传 trd_env=REAL。

        Args:
            code: 股票代码，如 "HK.00700"。
            price: 委托价格。
            qty: 委托数量（股）。
            trd_side: 买卖方向，BUY（买入）或 SELL（卖出），默认 BUY。
            order_type: 订单类型，如 NORMAL（限价单），默认 NORMAL。
            trd_env: 交易环境，SIMULATE（模拟，默认）或 REAL（实盘）。
            market: 市场，HK / US / CN，默认 HK。
        """
        return _guarded(lambda: _get_trade().place_order(
            code=code,
            price=price,
            qty=qty,
            order_type=order_type,
            trd_side=trd_side,
            trd_env=trd_env,
            market=market,
            enable_risk_check=True,
        ))

    return mcp
