"""回测引擎 P1 骨架测试：端到端运行、资金守恒、F1/F3 护栏、指标边界。

覆盖 P1 验收项：
  ① 合成数据 + MA 交叉信号跑通 ChinaAEngine，产出 equity + Sharpe/回撤等指标。
  ② F1：FetcherLoader 对缺失/非正 open 的帧报错（防未来函数）。
  ④ F3：小资金高价股整手取整归零时告警且不下单。
  ⑤ 资金守恒：全程收盘强平后 capital == initial + Σ(pnl - commission)。
  另含 metrics 边界（空/单根）与 gated 真实数据（TdxFetcher 可达时取 600000）。

遵循项目约定：unittest、不使用 mock（用手写 stub loader 喂真实合成 DataFrame）。
运行：``python -m unittest decidra.tests.test_backtest_engine``
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import pandas as pd

from decidra.strategy.backtest import (
    ChinaAEngine,
    CzscSignalEngine,
    FetcherLoader,
    GlobalEquityEngine,
    calc_metrics,
    run_and_persist,
)

ENGINE_LOGGER = "decidra.strategy.backtest.engine"


def _synthetic_ohlc(rows: int = 200, base_price: float = 100.0) -> pd.DataFrame:
    """合成日线 OHLCV（DatetimeIndex + 小写列 + pct_chg 百分点），趋势+震荡，无极端涨跌。"""
    idx = pd.bdate_range("2023-01-02", periods=rows)
    t = np.arange(rows, dtype=float)
    close = base_price * (1.0 + 0.15 * np.sin(t / 10.0) + 0.0003 * t)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = 1_000_000.0 + (t % 5) * 50_000.0
    pct_chg = pd.Series(close, index=idx).pct_change().fillna(0.0).to_numpy() * 100.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "pct_chg": pct_chg,
        },
        index=idx,
    )


class _DictLoader:
    """手写 stub loader：返回预置的合成 data_map（非 mock，数据真实）。"""

    name = "synthetic"

    def __init__(self, data_map: Dict[str, pd.DataFrame]) -> None:
        self._data_map = data_map

    def fetch(self, codes, start_date="", end_date="", *, fields=None, interval="1D"):
        del start_date, end_date, fields, interval
        return {c: self._data_map[c] for c in codes if c in self._data_map}


class _MaCrossSignal:
    """MA 交叉信号引擎：fast 上穿 slow 做多（1），否则空仓（0）。"""

    def __init__(self, fast: int = 5, slow: int = 20) -> None:
        self.fast = fast
        self.slow = slow

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        out: Dict[str, pd.Series] = {}
        for code, df in data_map.items():
            fast_ma = df["close"].rolling(self.fast).mean()
            slow_ma = df["close"].rolling(self.slow).mean()
            sig = pd.Series(0.0, index=df.index)
            sig[fast_ma > slow_ma] = 1.0
            out[code] = sig
        return out


class _ConstantLongSignal:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {c: pd.Series(1.0, index=df.index) for c, df in data_map.items()}


class TestEngineRunAndConservation(unittest.TestCase):
    """① 端到端跑通 + ⑤ 资金守恒。"""

    def test_china_a_end_to_end_and_conservation(self) -> None:
        code = "600000"
        initial = 1_000_000.0
        config = {
            "codes": [code],
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": initial,
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader({code: _synthetic_ohlc()})
        signal = _MaCrossSignal()

        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(config, loader, signal, Path(tmp), bars_per_year=252)

        # 指标齐全且有限
        for key in ("final_value", "total_return", "annual_return", "max_drawdown", "sharpe"):
            self.assertIn(key, metrics)
            self.assertTrue(np.isfinite(metrics[key]), f"{key} 非有限值")

        # MA 交叉应产生若干笔交易
        self.assertGreater(len(engine.trades), 0, "MA 交叉未产生任何交易")
        self.assertEqual(metrics["trade_count"], len(engine.trades))

        # 收盘强平后无残留持仓
        self.assertEqual(len(engine.positions), 0, "回测结束仍有未平仓持仓")

        # ⑤ 资金守恒：终值现金 == 初始 + Σ(pnl - commission)
        expected_final = initial + sum(t.pnl - t.commission for t in engine.trades)
        self.assertAlmostEqual(engine.capital, expected_final, delta=1e-4)
        self.assertAlmostEqual(metrics["final_value"], engine.capital, delta=1e-6)


class TestF1OpenGuard(unittest.TestCase):
    """② F1：open 缺失/非正必须报错（防未来函数）。"""

    def test_missing_open_column_raises(self) -> None:
        df = _synthetic_ohlc(rows=30).drop(columns=["open"]).reset_index().rename(columns={"index": "date"})
        with self.assertRaises(ValueError):
            FetcherLoader._standardize("X", df)

    def test_nan_open_raises(self) -> None:
        df = _synthetic_ohlc(rows=30).reset_index().rename(columns={"index": "date"})
        df.loc[5, "open"] = np.nan
        with self.assertRaisesRegex(ValueError, "F1"):
            FetcherLoader._standardize("X", df)

    def test_nonpositive_open_raises(self) -> None:
        df = _synthetic_ohlc(rows=30).reset_index().rename(columns={"index": "date"})
        df.loc[3, "open"] = 0.0
        with self.assertRaisesRegex(ValueError, "F1"):
            FetcherLoader._standardize("X", df)

    def test_valid_frame_standardizes(self) -> None:
        df = _synthetic_ohlc(rows=30).reset_index().rename(columns={"index": "date"})
        out = FetcherLoader._standardize("X", df)
        self.assertIsInstance(out.index, pd.DatetimeIndex)
        self.assertTrue(out.index.is_monotonic_increasing)
        for col in ("open", "high", "low", "close"):
            self.assertIn(col, out.columns)


class TestF3ZeroLotWarning(unittest.TestCase):
    """④ F3：小资金高价股整手取整归零时告警且不下单。"""

    def test_zero_lot_warns_and_no_trade(self) -> None:
        code = "600519"
        config = {
            "codes": [code],
            "start_date": "2023-01-02",
            "end_date": "2023-03-31",
            "initial_cash": 50.0,  # 远不足 100 股 @ ~1600
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader({code: _synthetic_ohlc(rows=40, base_price=1600.0)})
        signal = _ConstantLongSignal()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs(ENGINE_LOGGER, level="WARNING") as cm:
                engine.run_backtest(config, loader, signal, Path(tmp), bars_per_year=252)

        f3_warnings = [msg for msg in cm.output if "F3" in msg]
        self.assertEqual(len(f3_warnings), 1, "F3 告警应按标的去重（每标的仅一次）")
        self.assertEqual(len(engine.trades), 0, "资金不足却仍成交")


class TestMetricsEdge(unittest.TestCase):
    """metrics 边界：空/单根不崩溃。"""

    def test_empty_equity(self) -> None:
        m = calc_metrics(pd.Series(dtype=float), [], 1_000_000.0)
        self.assertEqual(m["final_value"], 1_000_000.0)
        self.assertEqual(m["trade_count"], 0)

    def test_single_bar(self) -> None:
        eq = pd.Series([1_000_000.0], index=[pd.Timestamp("2023-01-02")])
        m = calc_metrics(eq, [], 1_000_000.0)
        self.assertTrue(np.isfinite(m["sharpe"]))
        self.assertEqual(m["sharpe"], 0.0)


class TestMultiSymbolPortfolio(unittest.TestCase):
    """P3：多标的组合回测（共享资金池、权重归一）。"""

    def test_two_symbol_portfolio(self) -> None:
        codes = ["600000", "600519"]
        initial = 1_000_000.0
        config = {
            "codes": codes,
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": initial,
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader(
            {
                "600000": _synthetic_ohlc(base_price=100.0),
                "600519": _synthetic_ohlc(base_price=150.0),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(
                config, loader, _MaCrossSignal(), Path(tmp), bars_per_year=252
            )

        self.assertEqual(len(engine.positions), 0)
        self.assertIn("by_symbol", metrics)
        self.assertGreater(metrics["trade_count"], 0)
        # 资金守恒
        expected = initial + sum(t.pnl - t.commission for t in engine.trades)
        self.assertAlmostEqual(engine.capital, expected, delta=1e-3)
        # 全程资金非负（篮子二分缩放保证不超额下单）
        self.assertGreaterEqual(min(s.capital for s in engine.equity_snapshots), -1e-6)


class TestBenchmarkExcess(unittest.TestCase):
    """P3：外部基准超额（config["benchmark"] 经 loader 取基准收益）。"""

    def test_benchmark_excess_computed(self) -> None:
        code, bench = "600000", "000300"
        config = {
            "codes": [code],
            "benchmark": bench,
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": 1_000_000.0,
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader(
            {
                code: _synthetic_ohlc(base_price=100.0),
                bench: _synthetic_ohlc(base_price=3800.0),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(
                config, loader, _MaCrossSignal(), Path(tmp), bars_per_year=252
            )

        self.assertEqual(metrics.get("benchmark_ticker"), bench)
        self.assertTrue(np.isfinite(metrics["benchmark_return"]))
        self.assertTrue(np.isfinite(metrics["excess_return"]))
        self.assertTrue(np.isfinite(metrics["information_ratio"]))


class TestValidation(unittest.TestCase):
    """P3：validation（monte_carlo/bootstrap/walk_forward）触发与落盘。"""

    def test_validation_runs_and_persists(self) -> None:
        code = "600000"
        config = {
            "codes": [code],
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": 1_000_000.0,
            "validation": {
                "monte_carlo": {"n_simulations": 50, "seed": 1},
                "bootstrap": {"n_bootstrap": 50, "seed": 1},
                "walk_forward": {"n_windows": 3},
            },
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader({code: _synthetic_ohlc(rows=200)})
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            metrics = engine.run_backtest(
                config, loader, _MaCrossSignal(), run_dir, bars_per_year=252
            )
            self.assertIn("validation", metrics)
            for key in ("monte_carlo", "bootstrap", "walk_forward"):
                self.assertIn(key, metrics["validation"])
            self.assertTrue((run_dir / "artifacts" / "validation.json").is_file())


class TestF7HaltFfill(unittest.TestCase):
    """P3 / F7：停牌日目标仓位经 ffill 保持（不被误清零）。"""

    def test_align_holds_position_through_halt(self) -> None:
        from decidra.strategy.backtest.engine import _align

        a = _synthetic_ohlc(rows=60)
        b = _synthetic_ohlc(rows=60)
        halt_days = list(b.index[30:34])  # 4 个停牌日（< ffill_limit）
        b_halted = b.drop(index=halt_days)
        data_map = {"A": a, "B": b_halted}
        # A 空仓、B 全程持仓 1（停牌日 B 无自身 K 线，但在 A 的日历里）
        signal_map = {
            "A": pd.Series(0.0, index=a.index),
            "B": pd.Series(1.0, index=b_halted.index),
        }
        _dates, _close, pos_df, _ret = _align(data_map, signal_map, ["A", "B"])

        for d in halt_days:
            self.assertIn(d, pos_df.index)
            self.assertGreater(pos_df.loc[d, "B"], 0.0, "停牌日 B 仓位被误清零")


class TestRunAndPersist(unittest.TestCase):
    """P3：run_and_persist 落盘 summary.json + artifacts。"""

    def test_writes_summary_and_artifacts(self) -> None:
        code = "600000"
        config = {
            "codes": [code],
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": 1_000_000.0,
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader({code: _synthetic_ohlc(rows=200)})
        with tempfile.TemporaryDirectory() as tmp:
            metrics, run_dir = run_and_persist(
                engine,
                config,
                loader,
                _MaCrossSignal(),
                run_id="test_run",
                base_dir=Path(tmp),
                bars_per_year=252,
            )
            self.assertTrue((run_dir / "summary.json").is_file())
            self.assertTrue((run_dir / "artifacts" / "metrics.csv").is_file())
            self.assertTrue((run_dir / "artifacts" / "equity.csv").is_file())
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["run_id"], "test_run")
            self.assertEqual(summary["config"]["codes"], [code])
            self.assertIn("final_value", summary["metrics"])


class TestCzscSignalEngine(unittest.TestCase):
    """P2：CzscSignalEngine 契约（0/1 状态、索引对齐）与驱动引擎。"""

    def test_signal_contract_on_synthetic(self) -> None:
        code = "600000"
        df = _synthetic_ohlc(rows=200)
        out = CzscSignalEngine().generate({code: df})
        self.assertIn(code, out)
        series = out[code]
        self.assertTrue(series.index.equals(df.index))
        self.assertTrue(set(pd.unique(series)).issubset({0.0, 1.0}))

    def test_short_series_is_flat(self) -> None:
        df = _synthetic_ohlc(rows=10)
        series = CzscSignalEngine().generate({"X": df})["X"]
        self.assertTrue((series == 0.0).all())

    def test_drives_engine_end_to_end(self) -> None:
        code = "600000"
        config = {
            "codes": [code],
            "start_date": "2023-01-02",
            "end_date": "2023-12-31",
            "initial_cash": 1_000_000.0,
        }
        engine = ChinaAEngine(config)
        loader = _DictLoader({code: _synthetic_ohlc(rows=200)})
        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(
                config, loader, CzscSignalEngine(), Path(tmp), bars_per_year=252
            )
        self.assertTrue(np.isfinite(metrics["final_value"]))
        self.assertEqual(len(engine.positions), 0)


@unittest.skipUnless(
    __import__("os").environ.get("DECIDRA_RUN_NET_TESTS") == "1",
    "设 DECIDRA_RUN_NET_TESTS=1 且数据源可达时运行真实 czsc 回测",
)
class TestCzscBacktestReal(unittest.TestCase):
    """P2 gated：真实 600000 缠论买卖点回测出结果。"""

    def test_real_czsc_backtest(self) -> None:
        code = "600000"
        config = {
            "codes": [code],
            "start_date": "2022-01-01",
            "end_date": "2024-06-30",
            "initial_cash": 1_000_000.0,
        }
        try:
            loader = FetcherLoader()
            data_map = loader.fetch([code], config["start_date"], config["end_date"])
        except Exception as exc:  # noqa: BLE001 - 数据源不可达即跳过
            self.skipTest(f"数据源不可达：{exc}")

        signal_engine = CzscSignalEngine()
        series = signal_engine.generate(data_map)[code]
        self.assertTrue(set(pd.unique(series)).issubset({0.0, 1.0}))
        self.assertGreater(int((series == 1.0).sum()), 0, "czsc 未产出任何持仓")
        self.assertGreater(int((series.diff().abs() > 0).sum()), 0, "czsc 无状态切换")

        engine = ChinaAEngine(config)
        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(
                config, loader, signal_engine, Path(tmp), bars_per_year=252
            )
        self.assertGreater(metrics["trade_count"], 0, "czsc 买卖点未触发交易")
        self.assertEqual(len(engine.positions), 0)
        self.assertTrue(np.isfinite(metrics["sharpe"]))


@unittest.skipUnless(
    __import__("os").environ.get("DECIDRA_RUN_NET_TESTS") == "1",
    "设 DECIDRA_RUN_NET_TESTS=1 且 TdxFetcher 可达时运行真实取数回测",
)
class TestFetcherLoaderReal(unittest.TestCase):
    """gated：真实取 600000 日线并跑通 ChinaAEngine。"""

    def test_real_600000_backtest(self) -> None:
        code = "600000"
        config = {
            "codes": [code],
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
            "initial_cash": 1_000_000.0,
        }
        try:
            loader = FetcherLoader()
            data_map = loader.fetch([code], config["start_date"], config["end_date"])
        except Exception as exc:  # noqa: BLE001 - 数据源不可达即跳过
            self.skipTest(f"数据源不可达：{exc}")

        self.assertIn(code, data_map)
        self.assertGreater(len(data_map[code]), 50)

        engine = ChinaAEngine(config)
        with tempfile.TemporaryDirectory() as tmp:
            metrics = engine.run_backtest(
                config, loader, _MaCrossSignal(), Path(tmp), bars_per_year=252
            )
        self.assertTrue(np.isfinite(metrics["final_value"]))
        self.assertEqual(len(engine.positions), 0)


class TestBacktestCLI(unittest.TestCase):
    """P4：CLI 市场识别、混合市场保护、run_from_args 注入 loader 端到端。"""

    def test_detect_market(self) -> None:
        from decidra.strategy.backtest.__main__ import _detect_market

        self.assertEqual(_detect_market("600000"), "a")
        self.assertEqual(_detect_market("000001"), "a")
        self.assertEqual(_detect_market("300750"), "a")
        self.assertEqual(_detect_market("0700.HK"), "hk")
        self.assertEqual(_detect_market("HK.00700"), "hk")
        self.assertEqual(_detect_market("AAPL"), "us")

    def test_resolve_market_mixed(self) -> None:
        from decidra.strategy.backtest.__main__ import _resolve_market

        self.assertEqual(_resolve_market(["600000", "600519"], None), "a")
        with self.assertRaises(SystemExit):
            _resolve_market(["600000", "AAPL"], None)
        # --market 覆盖混合市场
        self.assertEqual(_resolve_market(["600000", "AAPL"], "a"), "a")

    def test_run_from_args_end_to_end(self) -> None:
        from decidra.strategy.backtest.__main__ import run_from_args

        code = "600000"
        loader = _DictLoader({code: _synthetic_ohlc(rows=200)})
        with tempfile.TemporaryDirectory() as tmp:
            metrics, run_dir = run_from_args(
                symbols=[code],
                start="2023-01-02",
                end="2023-12-31",
                strategy="czsc_resonance",
                loader=loader,
                run_id="cli_test",
                base_dir=Path(tmp),
            )
            self.assertTrue((run_dir / "summary.json").is_file())
            self.assertTrue((run_dir / "artifacts" / "metrics.csv").is_file())
            self.assertIn("final_value", metrics)

    def test_unknown_strategy_raises(self) -> None:
        from decidra.strategy.backtest.__main__ import _build_signal

        with self.assertRaises(SystemExit):
            _build_signal("no_such_strategy")

    def test_market_override_mismatch_warns(self) -> None:
        """L1：--market 覆盖异市场标的时告警（仍套用指定市场）。"""
        from decidra.strategy.backtest.__main__ import _resolve_market

        with self.assertLogs(
            "decidra.strategy.backtest.__main__", level="WARNING"
        ) as cm:
            resolved = _resolve_market(["600000", "AAPL"], "a")
        self.assertEqual(resolved, "a")
        self.assertTrue(any("AAPL" in msg for msg in cm.output))


class TestLoaderMarketRouting(unittest.TestCase):
    """港美股绕开 A 股链、直取 yfinance；A 股走 manager 链（修 Tdx 静默误取港股）。"""

    def _fake_manager_frame(self):
        return (
            _synthetic_ohlc(rows=30).reset_index().rename(columns={"index": "date"}),
            "faketdx",
        )

    def _loaders(self, calls):
        from decidra.strategy.backtest.loader import FetcherLoader

        def fake_yf(yf_code, start, end):
            calls["yf"].append(yf_code)
            return _synthetic_ohlc(rows=30)

        outer = self

        class _FakeManager:
            def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
                calls["mgr"].append(stock_code)
                return outer._fake_manager_frame()

        return FetcherLoader(manager=_FakeManager(), yfinance_fetch=fake_yf)

    def test_to_yfinance_code(self) -> None:
        from decidra.strategy.backtest.loader import _to_yfinance_code

        self.assertEqual(_to_yfinance_code("0700.HK"), "0700.HK")
        self.assertEqual(_to_yfinance_code("HK.00700"), "0700.HK")
        self.assertEqual(_to_yfinance_code("HK.09988"), "9988.HK")
        self.assertEqual(_to_yfinance_code("AAPL"), "AAPL")
        self.assertEqual(_to_yfinance_code("US.AAPL"), "AAPL")

    def test_hk_routes_to_yfinance_not_manager(self) -> None:
        calls = {"yf": [], "mgr": []}
        loader = self._loaders(calls)
        data = loader.fetch(["0700.HK"], "2023-01-02", "2023-03-01")
        self.assertEqual(calls["yf"], ["0700.HK"])  # 港股走 yfinance
        self.assertEqual(calls["mgr"], [])          # 未误入 A 股链（Tdx 静默误取的根因）
        self.assertEqual(loader.sources["0700.HK"], "yfinance")
        self.assertIn("0700.HK", data)

    def test_us_routes_to_yfinance(self) -> None:
        calls = {"yf": [], "mgr": []}
        loader = self._loaders(calls)
        loader.fetch(["AAPL"], "2023-01-02", "2023-03-01")
        self.assertEqual(calls["yf"], ["AAPL"])
        self.assertEqual(calls["mgr"], [])
        self.assertEqual(loader.sources["AAPL"], "yfinance")

    def test_a_share_routes_to_manager(self) -> None:
        calls = {"yf": [], "mgr": []}
        loader = self._loaders(calls)
        loader.fetch(["600000"], "2023-01-02", "2023-03-01")
        self.assertEqual(calls["mgr"], ["600000"])  # A 股走原链
        self.assertEqual(calls["yf"], [])
        self.assertEqual(loader.sources["600000"], "faketdx")


class TestJsonSafe(unittest.TestCase):
    """L3：_json_safe 处理 numpy 标量与 NaN/Inf。"""

    def test_numpy_and_nonfinite(self) -> None:
        from decidra.strategy.backtest.runner import _json_safe

        self.assertEqual(_json_safe(np.float64(1.5)), 1.5)
        self.assertIsNone(_json_safe(np.float64("nan")))
        self.assertIsNone(_json_safe(float("inf")))
        self.assertEqual(_json_safe(np.int64(3)), 3)
        self.assertIsInstance(_json_safe(np.int64(3)), int)
        nested = _json_safe({"a": np.float64(2.0), "b": [np.int64(1), float("nan")]})
        self.assertEqual(nested, {"a": 2.0, "b": [1, None]})


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
