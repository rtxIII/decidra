"""CzscSignalEngine：把 czsc 缠论买卖点适配为回测引擎的 signal 契约。

回测引擎期望 ``generate(data_map) -> Dict[str, pd.Series]``，每个 Series 值即该
根 K 线的**目标权重**（引擎 shift(1) 后按次根开盘价成交）。缠论买卖点是**事件**，
若只在触发根发 1、其余发 0，仓位会在触发次根即平——不符合择时持有语义。故本
引擎做成**状态保持**（v1 开关式）：买点 → 目标权重 1（持有），卖点 → 0（空仓），
其间保持上一状态。仅多空 0/1，A 股/港美股通用。

逐根**点内计算**（point-in-time）：增量 ``CZSC.update(bar)`` 到第 i 根后运行信号，
信号只反映截至第 i 根的结构；叠加引擎的 shift(1)（次根开盘成交）杜绝未来函数。

信号集与方向归类复用 ``czsc_resonance``（单一真源）：``_DEFAULT_SIGNALS`` 日线
买卖点集、``_run_bs_signals`` 触发计算、``_classify`` 按值 v1 段关键词判买/卖。
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import pandas as pd

from ...mcp_server.czsc_lite import CZSC, Freq, RawBar
from ..czsc_resonance import _DEFAULT_SIGNALS, _classify, _run_bs_signals

# czsc 结构（分型→笔）成形所需的最小 K 线数；不足则整段空仓。
_MIN_BARS = 30


def _df_to_bars(code: str, df: pd.DataFrame) -> list:
    """回测 OHLCV 帧（DatetimeIndex + 小写列）转 RawBar 列表，id 从 0 连续编号。"""
    bars = []
    for i, (dt, row) in enumerate(df.iterrows()):
        bars.append(
            RawBar(
                symbol=code,
                id=i,
                dt=pd.Timestamp(dt).to_pydatetime(),
                freq=Freq.D,
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                vol=float(row.get("volume", row.get("vol", 0.0))),
                amount=float(row.get("amount", 0.0)),
            )
        )
    return bars


def _net_direction(fired: Dict[str, str]) -> Optional[str]:
    """已触发信号 → 净方向 "BUY"/"SELL"/None（买卖并存或皆无时保持不变）。"""
    has_buy = any(_classify(v) == "BUY" for v in fired.values())
    has_sell = any(_classify(v) == "SELL" for v in fired.values())
    if has_buy and not has_sell:
        return "BUY"
    if has_sell and not has_buy:
        return "SELL"
    return None


class CzscSignalEngine:
    """缠论买卖点 → 逐根目标权重（0/1，状态保持）。

    Args:
        signals: 覆盖日线信号集（函数名序列），缺省用 ``_DEFAULT_SIGNALS``。
        params: 透传给各信号函数的参数（如 di / ma_type / timeperiod）。
        min_bars: 结构成形最小 K 线数，不足则该标的整段空仓。
    """

    def __init__(
        self,
        signals: Optional[Sequence[str]] = None,
        params: Optional[dict] = None,
        min_bars: int = _MIN_BARS,
    ) -> None:
        self.signal_names = tuple(signals) if signals else _DEFAULT_SIGNALS
        self.params = dict(params or {})
        self.min_bars = min_bars

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {code: self._signal_for(code, df) for code, df in data_map.items()}

    def _signal_for(self, code: str, df: pd.DataFrame) -> pd.Series:
        signal = pd.Series(0.0, index=df.index)
        bars = _df_to_bars(code, df)
        n = len(bars)
        if n < self.min_bars:
            return signal

        c = CZSC(bars[:1])
        state = 0.0
        for i in range(1, n):
            c.update(bars[i])
            direction = _net_direction(
                _run_bs_signals(c, self.signal_names, self.params)
            )
            if direction == "BUY":
                state = 1.0
            elif direction == "SELL":
                state = 0.0
            signal.iloc[i] = state
        return signal
