"""Decidra 回测子系统（移植自 HKUDS/Vibe-Trading `agent/backtest`，MIT）。

逐 bar 事件驱动回测引擎 + 绩效指标，纯 pandas/numpy，无第三方重依赖。

公共入口：
  - ``FetcherLoader``：Decidra 数据源链 → 引擎 loader 契约。
  - ``ChinaAEngine`` / ``GlobalEquityEngine``：A 股 / 港美股引擎。
  - ``BaseEngine``：抽象基类（逐 bar 执行 + 市场规则钩子）。
  - ``calc_metrics``：绩效指标。

signal_engine 契约：``generate(data_map) -> Dict[str, pd.Series]``（信号 1/-1/0）。
详见 ``ATTRIBUTION.md``。
"""

from __future__ import annotations

from .china_a import ChinaAEngine
from .engine import BaseEngine
from .global_equity import GlobalEquityEngine
from .loader import FetcherLoader
from .metrics import calc_metrics
from .models import EquitySnapshot, Position, TradeRecord
from .runner import BACKTEST_DIR, run_and_persist
from .signal import CzscSignalEngine

__all__ = [
    "BaseEngine",
    "ChinaAEngine",
    "GlobalEquityEngine",
    "FetcherLoader",
    "CzscSignalEngine",
    "run_and_persist",
    "BACKTEST_DIR",
    "calc_metrics",
    "TradeRecord",
    "Position",
    "EquitySnapshot",
]
