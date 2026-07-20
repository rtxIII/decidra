"""回测运行与结果落盘。

将一次回测落盘到 ``~/.decidra/backtest/<run_id>/``：
  - ``artifacts/``：引擎写出的 equity/positions/trades/metrics/ohlcv CSV。
  - ``summary.json``：本次运行的 run card（config + 标量指标 + 数据源 + 时间戳）。
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ...utils.global_vars import DECIDRA_PATH

# 回测结果根目录：~/.decidra/backtest/
BACKTEST_DIR: Path = DECIDRA_PATH / "backtest"


def _json_safe(value: Any) -> Any:
    """递归清洗为 json 可序列化：numpy 标量转原生、NaN/Inf → None。"""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def run_and_persist(
    engine: Any,
    config: Dict[str, Any],
    loader: Any,
    signal_engine: Any,
    *,
    run_id: Optional[str] = None,
    bars_per_year: int = 252,
    base_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Path]:
    """运行回测并把结果落盘到 ``~/.decidra/backtest/<run_id>/``。

    Args:
        engine: 已按市场实例化的引擎（ChinaAEngine / GlobalEquityEngine）。
        config: 回测配置（codes/start_date/end_date/initial_cash 等）。
        loader: 数据 loader（FetcherLoader 或注入的 stub）。
        signal_engine: 信号引擎（generate(data_map)->Dict[str,Series]）。
        run_id: 运行标识，缺省用时间戳。
        bars_per_year: 年化因子（日线 A/港/美股为 252）。
        base_dir: 落盘根目录，缺省 ``BACKTEST_DIR``（``~/.decidra/backtest``）。

    Returns:
        (metrics, run_dir)：指标字典与本次运行目录。
    """
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = (base_dir or BACKTEST_DIR) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics = engine.run_backtest(
        config, loader, signal_engine, run_dir, bars_per_year=bars_per_year
    )

    summary = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "config": dict(config),
        "data_sources": getattr(loader, "sources", None) or {"loader": getattr(loader, "name", "")},
        # 仅保留标量指标（by_symbol/by_exit_reason/validation 等嵌套结构随 artifacts 落盘）。
        "metrics": {k: v for k, v in metrics.items() if not isinstance(v, dict)},
    }
    (run_dir / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metrics, run_dir
