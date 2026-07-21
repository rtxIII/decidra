"""回测命令行入口。

用法::

    python -m decidra.strategy.backtest run \\
        --symbol 600000 [--symbol 600519] --start 2023-01-01 --end 2024-06-30 \\
        [--strategy czsc_resonance] [--cash 1000000] [--benchmark 000300] \\
        [--market a|hk|us] [--validation] [--run-id NAME]

按标的代码自动选引擎（6 位数字→A股 ChinaAEngine；``.HK``→港股；其余→美股，
后两者用 GlobalEquityEngine），经 FetcherLoader 取数、CzscSignalEngine 生成缠论
买卖点信号，跑回测并落盘到 ``~/.decidra/backtest/<run_id>/``。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from .china_a import ChinaAEngine
from .global_equity import GlobalEquityEngine
from .loader import FetcherLoader, detect_market as _detect_market
from .runner import run_and_persist
from .signal import CzscSignalEngine

logger = logging.getLogger(__name__)

_STRATEGIES = ("czsc_resonance",)


def _resolve_market(symbols: Sequence[str], override: Optional[str]) -> str:
    """确定单一引擎市场；混合市场且未指定 --market 时报错（组合引擎未移植）。

    ``--market`` 覆盖时，对自动识别与之不符的标的告警：该引擎的市场规则
    （如 A 股 T+1/涨跌停）会被套用到这些异市场标的，可能不当。
    """
    if override:
        mismatched = [c for c in symbols if _detect_market(c) != override]
        if mismatched:
            logger.warning(
                "--market=%s 将套用于自动识别为其它市场的标的 %s，其市场规则可能不匹配",
                override,
                mismatched,
            )
        return override
    markets = {_detect_market(c) for c in symbols}
    if len(markets) > 1:
        raise SystemExit(
            f"混合市场 {sorted(markets)}：请用 --market 指定单一引擎，或分开回测"
        )
    return markets.pop()


def _build_engine(market: str, config: Dict[str, Any]) -> Any:
    if market == "a":
        return ChinaAEngine(config)
    if market in ("hk", "us"):
        return GlobalEquityEngine(config, market=market)
    raise SystemExit(f"未知市场: {market}")


def _build_signal(strategy: str) -> Any:
    if strategy == "czsc_resonance":
        return CzscSignalEngine()
    raise SystemExit(f"未知策略: {strategy}（可选: {', '.join(_STRATEGIES)}）")


def run_from_args(
    *,
    symbols: Sequence[str],
    start: str,
    end: str,
    strategy: str = "czsc_resonance",
    cash: float = 1_000_000.0,
    benchmark: Optional[str] = None,
    market: Optional[str] = None,
    validation: bool = False,
    run_id: Optional[str] = None,
    base_dir: Optional[Path] = None,
    loader: Any = None,
) -> Tuple[Dict[str, Any], Path]:
    """按参数构建配置/引擎/信号并运行落盘（loader 可注入以便无网络测试）。"""
    resolved_market = _resolve_market(symbols, market)
    config: Dict[str, Any] = {
        "codes": list(symbols),
        "start_date": start,
        "end_date": end,
        "initial_cash": cash,
    }
    if benchmark:
        config["benchmark"] = benchmark
    if validation:
        config["validation"] = {"monte_carlo": {}, "bootstrap": {}, "walk_forward": {}}

    engine = _build_engine(resolved_market, config)
    signal_engine = _build_signal(strategy)
    loader = loader or FetcherLoader()
    return run_and_persist(
        engine, config, loader, signal_engine, run_id=run_id, base_dir=base_dir
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Decidra 回测 Runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="运行一次回测并落盘")
    run_parser.add_argument(
        "--symbol", action="append", dest="symbols", required=True,
        help="标的代码（可重复传多个组成组合），如 600000 / 0700.HK / AAPL",
    )
    run_parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    run_parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    run_parser.add_argument(
        "--strategy", default="czsc_resonance", choices=list(_STRATEGIES),
        help="信号策略（默认 czsc_resonance）",
    )
    run_parser.add_argument("--cash", type=float, default=1_000_000.0, help="初始资金")
    run_parser.add_argument("--benchmark", default=None, help="基准标的代码（可选）")
    run_parser.add_argument(
        "--market", default=None, choices=["a", "hk", "us"],
        help="强制指定引擎市场（混合市场组合必填）",
    )
    run_parser.add_argument("--validation", action="store_true", help="启用稳健性校验")
    run_parser.add_argument("--run-id", default=None, dest="run_id", help="运行标识（默认时间戳）")

    args = parser.parse_args(argv)

    metrics, run_dir = run_from_args(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        strategy=args.strategy,
        cash=args.cash,
        benchmark=args.benchmark,
        market=args.market,
        validation=args.validation,
        run_id=args.run_id,
    )
    scalar = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
    print(json.dumps({"run_dir": str(run_dir), "metrics": scalar}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
