"""缠论（czsc）信号分析 MCP 服务器（stdio）。

以 MCP 工具形式把 czsc_lite（从 czsc fork 的缠论信号分析核心）暴露给终端 agent。
数据源用 yfinance（免费，覆盖全球股票），OHLCV → RawBar → CZSC → 运行缠论信号。

零重依赖：仅 numpy/pandas/scikit-learn/yfinance（均已随 Decidra 安装）。

启动: ``python -m decidra.mcp_server.czsc_server``
"""

from __future__ import annotations

import concurrent.futures
import json
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

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

# 精选缠论信号（买卖点 / 笔状态 / 趋势），返回值非“其他”即视为触发。
_CURATED_SIGNALS = [
    "cxt_third_buy_V230228",
    "cxt_third_bs_V230318",
    "cxt_second_bs_V230320",
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


def _build_czsc(symbol: str, period: str, freq_name: str):
    """用 yfinance 取 K 线并构建 CZSC 对象。"""
    import yfinance as yf
    from .czsc_lite import CZSC, RawBar, Freq

    freq_val, interval = _FREQ_MAP.get(freq_name, ("D", "1d"))
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df is None or df.empty:
        raise ValueError(f"未取到 {symbol} 的 K 线数据")

    freq_enum = {"D": Freq.D, "W": Freq.W, "M": Freq.M,
                 "60分钟": Freq.F60, "30分钟": Freq.F30, "15分钟": Freq.F15}.get(freq_val, Freq.D)
    bars = []
    for i, (idx, row) in enumerate(df.iterrows()):
        dt = idx.to_pydatetime().replace(tzinfo=None)
        bars.append(RawBar(
            symbol=symbol, id=i, dt=dt, freq=freq_enum,
            open=float(row["Open"]), close=float(row["Close"]),
            high=float(row["High"]), low=float(row["Low"]),
            vol=float(row["Volume"]), amount=float(row["Close"] * row["Volume"]),
        ))
    return CZSC(bars)


def build_server() -> FastMCP:
    """构建缠论 MCP 服务器并注册工具。"""
    mcp = FastMCP("czsc")

    @mcp.tool()
    def czsc_chan_analysis(symbol: str, period: str = "1y", freq: str = "日线") -> str:
        """对股票做缠论（czsc）分析：分型/笔/中枢结构 + 精选买卖点信号。

        用 yfinance 取 K 线（覆盖全球股票，如 AAPL、MSFT；港股用 0700.HK；A股用
        600519.SS/000001.SZ），构建缠论结构，运行精选缠论信号并返回已触发的信号。

        Args:
            symbol: yfinance 股票代码，如 "AAPL"、"0700.HK"、"600519.SS"。
            period: 数据周期，如 "6mo" / "1y" / "2y"，默认 "1y"。
            freq: K 线级别，可选 日线/周线/月线/60分钟/30分钟/15分钟，默认 日线。
        """
        def _run():
            c = _build_czsc(symbol, period, freq)
            from .czsc_lite import signals_cxt as cxt

            fired = {}
            for name in _CURATED_SIGNALS:
                fn = getattr(cxt, name, None)
                if fn is None:
                    continue
                try:
                    sig = dict(fn(c))
                    for k, v in sig.items():
                        # 值以 "其他_..." 开头视为未触发
                        if not str(v).startswith("其他"):
                            fired[k] = v
                except Exception:
                    continue

            last_bi = c.bi_list[-1] if c.bi_list else None
            summary = {
                "symbol": symbol,
                "freq": freq,
                "bars": len(c.bars_raw),
                "fx_count": len(c.fx_list),
                "bi_count": len(c.bi_list),
                "last_bi_direction": last_bi.direction.value if last_bi else None,
                "last_bi_high": round(last_bi.high, 4) if last_bi else None,
                "last_bi_low": round(last_bi.low, 4) if last_bi else None,
                "fired_signals": fired,
            }
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
