"""缠论（czsc）信号分析 MCP 服务器（stdio）。

以 MCP 工具形式把 czsc_lite（从 czsc fork 的缠论信号分析核心）暴露给终端 agent。
数据源用 yfinance（免费，覆盖全球股票），OHLCV → RawBar → CZSC → 运行缠论信号。

零重依赖：仅 numpy/pandas/scikit-learn/yfinance（均已随 Decidra 安装）。

启动: ``python -m decidra.mcp_server.czsc_server``
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

# stdio 传输下 stdout 专供 MCP 协议，日志经 logging 走 stderr，不污染协议通道。
_LOG = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS: float = 20.0
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="czsc-tool")

# 频率名 → czsc Freq 值 与 yfinance interval 的映射。
_FREQ_MAP = {
    "日线": ("D", "1d"),
    "周线": ("W", "1wk"),
    "月线": ("M", "1mo"),
    "60分钟": ("60分钟", "60m"),
    "30分钟": ("30分钟", "30m"),
    "15分钟": ("15分钟", "15m"),
}

# 精选缠论信号（买卖点 / 笔状态 / 趋势 / 中枢），返回值非“其他”即视为触发。
# 全部使用 "其他" 作为未触发哨兵，与下方过滤逻辑一致。
_CURATED_SIGNALS = [
    # 买卖点：一/二/三类买卖点（缠论核心反转与延续信号）
    "cxt_first_buy_V221126",
    "cxt_first_sell_V221126",
    "cxt_second_bs_V230320",
    "cxt_third_buy_V230228",
    "cxt_third_bs_V230318",
    # 中枢结构（仅收录单级别 CZSC 信号；zhong_shu_gong_zhen 为多级别信号，
    # 由 czsc_multi_level_analysis 的跨级别共振环节单独调用）
    "cxt_double_zs_V230311",
    # 笔状态 / 趋势 / 笔数结构
    "cxt_bi_status_V230101",
    "cxt_bi_end_V230618",
    "cxt_bi_trend_V230824",
    "cxt_three_bi_V230618",
    "cxt_five_bi_V230619",
]


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": str(message)}, ensure_ascii=False)


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _guarded(call: Callable[[], Any]) -> str:
    """超时保护执行（缠论计算可能较慢）。"""
    try:
        future = _EXECUTOR.submit(call)
        return future.result(timeout=TOOL_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        return _err(f"缠论分析超时（>{TOOL_TIMEOUT_SECONDS:.0f}s）")
    except Exception as exc:
        return _err(exc)


def _fetch_kline_df(symbol: str, period: str, interval: str = "1d"):
    """用 yfinance 取 K 线并标准化为 czsc 列（symbol/dt/open/close/high/low/vol/amount）。

    Returns:
        (df, issues)：标准化 DataFrame 与数据质量问题摘要（无问题为空列表）。
    """
    import pandas as pd
    import yfinance as yf
    from .czsc_lite import summarize_kline_quality

    raw = yf.Ticker(symbol).history(period=period, interval=interval)
    if raw is None or raw.empty:
        raise ValueError(f"未取到 {symbol} 的 K 线数据")

    df = pd.DataFrame({
        "symbol": symbol,
        "dt": [idx.to_pydatetime().replace(tzinfo=None) for idx in raw.index],
        "open": raw["Open"].astype(float).values,
        "close": raw["Close"].astype(float).values,
        "high": raw["High"].astype(float).values,
        "low": raw["Low"].astype(float).values,
        "vol": raw["Volume"].astype(float).values,
    })
    df["amount"] = df["close"] * df["vol"]

    issues = summarize_kline_quality(df)
    if issues:
        _LOG.warning("K线质量问题 %s(%s): %s", symbol, interval, issues)
    return df, issues


def _bars_from_df(df, freq_enum) -> list:
    """标准化 K 线 DataFrame 转 RawBar 列表（共享实现见 czsc_lite.bars_from_df）。"""
    from .czsc_lite import bars_from_df

    return bars_from_df(df, freq_enum)


def _build_czsc(symbol: str, period: str, freq_name: str):
    """用 yfinance 取 K 线并构建 CZSC 对象。"""
    from .czsc_lite import CZSC, Freq

    freq_val, interval = _FREQ_MAP.get(freq_name, ("D", "1d"))
    freq_enum = {"D": Freq.D, "W": Freq.W, "M": Freq.M,
                 "60分钟": Freq.F60, "30分钟": Freq.F30, "15分钟": Freq.F15}.get(freq_val, Freq.D)
    df, _ = _fetch_kline_df(symbol, period, interval)
    return CZSC(_bars_from_df(df, freq_enum))


def _run_curated_signals(c, signal_params: dict) -> dict:
    """运行全部精选信号，返回已触发（值非“其他”开头）的信号。"""
    from .czsc_lite import signals_cxt as cxt

    fired = {}
    for name in _CURATED_SIGNALS:
        fn = getattr(cxt, name, None)
        if fn is None:
            continue
        try:
            sig = dict(fn(c, **signal_params))
        except Exception as exc:
            # 单个信号在特定标的/数据上报错不应中断整体分析；记日志便于排查
            _LOG.debug("缠论信号 %s 计算失败: %s", name, exc)
            continue
        for k, v in sig.items():
            # 值以 "其他_..." 开头视为未触发
            if not str(v).startswith("其他"):
                fired[k] = v
    return fired


def _structure_summary(c) -> dict:
    """CZSC 对象的缠论结构摘要。"""
    last_bi = c.bi_list[-1] if c.bi_list else None
    return {
        "bars": len(c.bars_raw),
        "fx_count": len(c.fx_list),
        "bi_count": len(c.bi_list),
        "last_bi_direction": last_bi.direction.value if last_bi else None,
        "last_bi_high": round(last_bi.high, 4) if last_bi else None,
        "last_bi_low": round(last_bi.low, 4) if last_bi else None,
    }


def build_server() -> FastMCP:
    """构建缠论 MCP 服务器并注册工具。"""
    mcp = FastMCP("czsc")

    @mcp.tool()
    def czsc_chan_analysis(
        symbol: str, period: str = "1y", freq: str = "日线", params: dict | None = None
    ) -> str:
        """对股票做缠论（czsc）分析：分型/笔/中枢结构 + 精选买卖点信号。

        用 yfinance 取 K 线（覆盖全球股票，如 AAPL、MSFT；港股用 0700.HK；A股用
        600519.SS/000001.SZ），构建缠论结构，运行精选缠论信号并返回已触发的信号。

        Args:
            symbol: yfinance 股票代码，如 "AAPL"、"0700.HK"、"600519.SS"。
            period: 数据周期，如 "6mo" / "1y" / "2y"，默认 "1y"。
            freq: K 线级别，可选 日线/周线/月线/60分钟/30分钟/15分钟，默认 日线。
            params: 可选，透传给全部精选信号的参数（信号忽略不认识的键）。常用：
                ``di``（回溯第几笔，默认 1，越大越靠历史）；``ma_type``/``timeperiod``
                （二/三类买卖点的均线类型与周期，如 {"ma_type":"EMA","timeperiod":21}）；
                ``max_overlap``（笔终结容差）、``n``/``th``（趋势阈值）。
                示例：{"di": 2, "timeperiod": 21}。参数非法的信号会被跳过。
        """
        signal_params = params or {}

        def _run():
            c = _build_czsc(symbol, period, freq)
            fired = _run_curated_signals(c, signal_params)
            summary = {"symbol": symbol, "freq": freq, **_structure_summary(c), "fired_signals": fired}
            return _ok(summary)

        return _guarded(_run)

    @mcp.tool()
    def czsc_multi_level_analysis(
        symbol: str, period: str = "5y", freqs: list[str] | None = None, params: dict | None = None
    ) -> str:
        """多级别缠论联立分析：日线取数本地重采样出周线/月线，逐级别结构+信号，附跨级别中枢共振。

        用 yfinance 取日线 K 线后在本地重采样合成大级别（各级别数据同源），对每个级别
        构建缠论结构并运行精选信号；再对相邻大小级别运行中枢共振信号（类二买共振），
        用于回答“日线买点与周线趋势是否共振”这类级别联立问题。

        Args:
            symbol: yfinance 股票代码，如 "AAPL"、"0700.HK"、"600519.SS"。
            period: 数据周期，默认 "5y"（月线级别需要足够年限才能形成笔）。
            freqs: 参与联立的级别列表，默认 ["日线", "周线", "月线"]，仅支持这三个。
            params: 可选，透传给全部精选信号的参数，同 czsc_chan_analysis。
        """
        level_names = freqs or ["日线", "周线", "月线"]
        signal_params = params or {}

        def _run():
            from types import SimpleNamespace

            from .czsc_lite import CZSC, Freq, resample_bars
            from .czsc_lite import signals_cxt as cxt

            freq_enum_map = {"日线": Freq.D, "周线": Freq.W, "月线": Freq.M}
            unknown = [n for n in level_names if n not in freq_enum_map]
            if unknown:
                raise ValueError(f"多级别分析仅支持 日线/周线/月线，收到: {unknown}")

            df, quality_issues = _fetch_kline_df(symbol, period)
            kas = {}
            levels = {}
            for name in level_names:
                freq_enum = freq_enum_map[name]
                if freq_enum == Freq.D:
                    bars = _bars_from_df(df, Freq.D)
                else:
                    bars = resample_bars(df, freq_enum, raw_bars=True)
                c = CZSC(bars)
                kas[name] = c
                levels[name] = {
                    **_structure_summary(c),
                    "fired_signals": _run_curated_signals(c, signal_params),
                }

            # 相邻大小级别的中枢共振（大级别在前）
            cat = SimpleNamespace(kas=kas, symbol=symbol)
            cross = {}
            order = [n for n in ("月线", "周线", "日线") if n in kas]
            for big, small in zip(order, order[1:]):
                sig = dict(cxt.cxt_zhong_shu_gong_zhen_V221221(cat, freq1=big, freq2=small))
                for k, v in sig.items():
                    if not str(v).startswith("其他"):
                        cross[k] = v

            summary = {
                "symbol": symbol,
                "period": period,
                "levels": levels,
                "cross_level_signals": cross,
            }
            if quality_issues:
                summary["data_quality_issues"] = quality_issues
            return _ok(summary)

        return _guarded(_run)

    @mcp.tool()
    def czsc_list_signals() -> str:
        """列出可用的缠论信号函数名与说明摘要。"""
        def _run():
            from .czsc_lite import signals_cxt as cxt
            import inspect
            out = []
            for name, fn in inspect.getmembers(cxt, inspect.isfunction):
                if name.startswith("cxt_"):
                    doc = (fn.__doc__ or "").strip().splitlines()
                    out.append({"name": name, "desc": doc[0] if doc else ""})
            return _ok({"count": len(out), "signals": out})

        return _guarded(_run)

    return mcp


def main() -> None:
    """以 stdio 传输运行缠论 MCP 服务器。

    ``run`` 在父进程关闭 stdio 后返回；随后 ``os._exit`` 强制退出，确保子进程被
    openharness 干净回收（与 futu/yfinance server 一致）。
    """
    import os
    try:
        build_server().run(transport="stdio")
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
