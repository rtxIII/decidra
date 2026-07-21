"""evals（告警/研判结果回收与评测）单元测试。

不 mock：合成收盘价 Series 经 ``fetch_closes_fn`` 注入、临时目录隔离
alerts/outcomes/enrichments 文件；真实历史回填经 ``DECIDRA_RUN_NET_TESTS=1`` gated。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from decidra.strategy import config as config_mod
from decidra.strategy import evals
from decidra.strategy.alerts import Alert, append_alerts
from decidra.tasks import registry


def _closes(dates, values):
    return pd.Series(values, index=pd.to_datetime(dates))


# horizon=3 的评测配置（缩短便于构造样本）
_EVALS_CONFIG = {
    "evals": {
        "enabled": True,
        "horizon_days": 3,
        "report_window": 90,
        "schedule": "0 22 * * *",
    }
}


class TestForwardPricing(unittest.TestCase):
    """_forward_from_closes 纯函数：锚后第 N 根定位。"""

    def setUp(self):
        self.closes = _closes(
            ["2024-06-24", "2024-06-25", "2024-06-26", "2024-06-27",
             "2024-06-28", "2024-07-01", "2024-07-02"],
            [10.0, 10.2, 10.5, 10.3, 11.0, 11.5, 12.0],
        )

    def test_nth_bar_after_anchor(self):
        # 锚 06-25(=10.2)，第 3 根后续 = 06-28(=11.0)
        res = evals._forward_from_closes(self.closes, pd.Timestamp("2024-06-25"), 3)
        self.assertIsNotNone(res)
        priced_from, priced_to, priced_to_dt = res
        self.assertAlmostEqual(priced_from, 10.2)
        self.assertAlmostEqual(priced_to, 11.0)
        self.assertEqual(priced_to_dt[:10], "2024-06-28")

    def test_exactly_n_bars_boundary(self):
        # 锚 06-27，后续恰好 3 根(06-28/07-01/07-02) → 第 3 根 07-02
        res = evals._forward_from_closes(self.closes, pd.Timestamp("2024-06-27"), 3)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[1], 12.0)

    def test_insufficient_bars_pending(self):
        # 锚 07-01，后续仅 1 根 → 不足 N，pending(None)
        res = evals._forward_from_closes(self.closes, pd.Timestamp("2024-07-01"), 3)
        self.assertIsNone(res)

    def test_anchor_day_missing_priced_from_none(self):
        # 锚 06-25 不在帧内 → priced_from None（由调用方 snapshot 兜底）
        frame = self.closes[self.closes.index != pd.Timestamp("2024-06-25")]
        res = evals._forward_from_closes(frame, pd.Timestamp("2024-06-25"), 3)
        self.assertIsNotNone(res)
        self.assertIsNone(res[0])

    def test_halt_gap_counts_by_bars(self):
        # 停牌：日历跳过一周，第 N 根仍按 K 线根数（非自然日）定位
        halted = _closes(
            ["2024-06-25", "2024-06-26", "2024-07-10", "2024-07-11"],
            [10.0, 10.5, 12.0, 12.5],
        )
        res = evals._forward_from_closes(halted, pd.Timestamp("2024-06-25"), 3)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[1], 12.5)  # 第 3 根后续 = 07-11


class TestMarketRouting(unittest.TestCase):
    """_to_market_and_code：富途码 → (市场, fetcher 码)。"""

    def test_a_share(self):
        self.assertEqual(evals._to_market_and_code("SH.600000"), ("a", "600000"))
        self.assertEqual(evals._to_market_and_code("SZ.000001"), ("a", "000001"))

    def test_hk_zero_padding(self):
        self.assertEqual(evals._to_market_and_code("HK.00700"), ("hk", "0700.HK"))
        self.assertEqual(evals._to_market_and_code("HK.09988"), ("hk", "9988.HK"))

    def test_us(self):
        self.assertEqual(evals._to_market_and_code("US.AAPL"), ("us", "AAPL"))

    def test_unknown_prefix_raises(self):
        with self.assertRaises(ValueError):
            evals._to_market_and_code("600000")


class _EvalsFileCase(unittest.TestCase):
    """临时目录承载 alerts/outcomes/enrichments，隔离真实运行目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.alerts_path = base / "alerts.jsonl"
        self.outcomes_path = base / "outcomes.json"
        self.enrichments_path = base / "enrichments.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_alert(self, alert_id, symbol, action, bar_dt, last_close):
        append_alerts(
            [Alert(
                dt="2024-06-25T09:30:00", symbol=symbol, strategy="czsc_resonance",
                action=action, reason="test", bar_dt=bar_dt,
                snapshot={"last_close": last_close}, id=alert_id,
            )],
            self.alerts_path,
        )


class TestBackfill(_EvalsFileCase):

    def _fetch(self, series_by_symbol):
        def fetch(symbol, anchor_dt, now):
            return series_by_symbol.get(symbol)
        return fetch

    def _run(self, fetch_fn):
        return evals.backfill(
            now=datetime(2024, 7, 5),
            config=_EVALS_CONFIG,
            alerts_path=self.alerts_path,
            outcomes_path=self.outcomes_path,
            fetch_closes_fn=fetch_fn,
        )

    def test_buy_rising_hits(self):
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.2)
        series = _closes(
            ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"],
            [10.2, 10.5, 10.7, 11.0],
        )
        summary = self._run(self._fetch({"SH.600000": series}))
        self.assertEqual(summary["priced"], 1)
        outcome = evals.load_outcomes(self.outcomes_path)["buy1"]
        self.assertTrue(outcome["direction_correct"])
        self.assertGreater(outcome["forward_return"], 0)

    def test_sell_falling_hits(self):
        # SELL 后跌为命中，forward_return 取反号为正
        self._write_alert("sell1", "SH.600000", "SELL", "2024-06-25T00:00:00", 11.0)
        series = _closes(
            ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"],
            [11.0, 10.5, 10.2, 10.0],
        )
        summary = self._run(self._fetch({"SH.600000": series}))
        self.assertEqual(summary["priced"], 1)
        outcome = evals.load_outcomes(self.outcomes_path)["sell1"]
        self.assertTrue(outcome["direction_correct"])
        self.assertGreater(outcome["forward_return"], 0)

    def test_buy_falling_misses(self):
        self._write_alert("buy2", "SH.600000", "BUY", "2024-06-25T00:00:00", 11.0)
        series = _closes(
            ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"],
            [11.0, 10.5, 10.2, 10.0],
        )
        self._run(self._fetch({"SH.600000": series}))
        outcome = evals.load_outcomes(self.outcomes_path)["buy2"]
        self.assertFalse(outcome["direction_correct"])
        self.assertLess(outcome["forward_return"], 0)

    def test_idempotent_no_recompute(self):
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.2)
        series = _closes(
            ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"],
            [10.2, 10.5, 10.7, 11.0],
        )
        fetch = self._fetch({"SH.600000": series})
        self.assertEqual(self._run(fetch)["priced"], 1)
        second = self._run(fetch)  # 已有 outcome，不重算
        self.assertEqual(second["priced"], 0)

    def test_pending_not_written(self):
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.2)
        series = _closes(["2024-06-25", "2024-06-26"], [10.2, 10.5])  # 后续仅 1 根
        summary = self._run(self._fetch({"SH.600000": series}))
        self.assertEqual(summary["priced"], 0)
        self.assertEqual(summary["pending"], 1)
        self.assertFalse(self.outcomes_path.exists())

    def test_fetch_error_isolated(self):
        self._write_alert("ok1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.2)
        self._write_alert("bad1", "SH.600001", "BUY", "2024-06-25T00:00:00", 10.2)
        good = _closes(
            ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"],
            [10.2, 10.5, 10.7, 11.0],
        )

        def fetch(symbol, anchor_dt, now):
            if symbol == "SH.600001":
                raise ValueError("取数失败")
            return good

        summary = self._run(fetch)
        self.assertEqual(summary["priced"], 1)
        self.assertIn("bad1", summary["errors"])
        self.assertIn("ok1", evals.load_outcomes(self.outcomes_path))

    def test_snapshot_fallback_when_anchor_missing(self):
        # 取数帧缺锚日 → priced_from 用 snapshot.last_close 兜底
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.0)
        series = _closes(
            ["2024-06-26", "2024-06-27", "2024-06-28"], [10.5, 10.7, 11.0]
        )
        self._run(self._fetch({"SH.600000": series}))
        outcome = evals.load_outcomes(self.outcomes_path)["buy1"]
        self.assertAlmostEqual(outcome["priced_from"], 10.0)  # 来自 snapshot

    def test_no_anchor_price_skipped(self):
        # 帧缺锚日且 snapshot 无 last_close → 无法定价，skipped
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", None)
        series = _closes(
            ["2024-06-26", "2024-06-27", "2024-06-28"], [10.5, 10.7, 11.0]
        )
        summary = self._run(self._fetch({"SH.600000": series}))
        self.assertEqual(summary["priced"], 0)
        self.assertEqual(summary["skipped"], 1)


class TestReport(_EvalsFileCase):

    def _write_outcomes(self, outcomes):
        self.outcomes_path.write_text(
            json.dumps(outcomes, ensure_ascii=False), encoding="utf-8"
        )

    def _write_enrichments(self, enrichments):
        self.enrichments_path.write_text(
            json.dumps(enrichments, ensure_ascii=False), encoding="utf-8"
        )

    def _make_outcome(self, symbol, action, bar_dt, correct, ret=0.05):
        return {
            "symbol": symbol, "action": action, "bar_dt": bar_dt,
            "horizon_days": 3, "priced_from": 10.0, "priced_to": 10.5,
            "forward_return": ret, "direction_correct": correct,
            "priced_at": "2024-07-01T00:00:00",
        }

    def _report(self):
        return evals.report(
            now=datetime(2024, 7, 5), config=_EVALS_CONFIG,
            outcomes_path=self.outcomes_path,
            enrichments_path=self.enrichments_path,
        )

    def test_signal_hit_rate(self):
        # 6 条信号，4 命中 → 命中率 0.6667
        outcomes = {}
        for i in range(6):
            outcomes[f"a{i}"] = self._make_outcome(
                f"SH.60000{i}", "BUY", "2024-06-25T00:00:00", correct=i < 4
            )
        self._write_outcomes(outcomes)
        report = self._report()
        self.assertEqual(report["signal_hit_rate"]["n"], 6)
        self.assertAlmostEqual(report["signal_hit_rate"]["rate"], round(4 / 6, 4))

    def test_dedupe_same_signal(self):
        # 同 (symbol, action, bar_dt) 两 id（转正）→ 计一次
        outcomes = {
            "a0": self._make_outcome("SH.600000", "BUY", "2024-06-25T00:00:00", True),
            "a0b": self._make_outcome("SH.600000", "BUY", "2024-06-25T00:00:00", True),
        }
        # 补足样本量到阈值
        for i in range(1, 5):
            outcomes[f"b{i}"] = self._make_outcome(
                f"SZ.00000{i}", "BUY", "2024-06-26T00:00:00", True
            )
        self._write_outcomes(outcomes)
        report = self._report()
        self.assertEqual(report["signal_hit_rate"]["n"], 5)  # 6 条去重成 5

    def test_insufficient_sample_null(self):
        self._write_outcomes({
            "a0": self._make_outcome("SH.600000", "BUY", "2024-06-25T00:00:00", True)
        })
        report = self._report()
        self.assertIsNone(report["signal_hit_rate"]["rate"])
        self.assertEqual(report["signal_hit_rate"]["n"], 1)

    def test_window_filter(self):
        # 窗口外 bar_dt 不计入
        outcomes = {
            "old": self._make_outcome("SH.600000", "BUY", "2023-01-01T00:00:00", True),
        }
        for i in range(5):
            outcomes[f"n{i}"] = self._make_outcome(
                f"SZ.00000{i}", "BUY", "2024-06-25T00:00:00", True
            )
        self._write_outcomes(outcomes)
        report = self._report()
        self.assertEqual(report["signal_hit_rate"]["n"], 5)  # old 被窗口过滤

    def test_enriched_and_veto_and_calibration(self):
        outcomes, enrichments = {}, {}
        # 5 条"支持"研判，3 命中 → enriched_hit_rate 0.6
        for i in range(5):
            aid = f"sup{i}"
            outcomes[aid] = self._make_outcome(
                f"SH.60000{i}", "BUY", "2024-06-25T00:00:00", correct=i < 3
            )
            enrichments[aid] = {"conclusion": "支持", "confidence": "高"}
        # 5 条"反对"研判，4 未命中 → veto_avoid_rate 0.8
        for i in range(5):
            aid = f"opp{i}"
            outcomes[aid] = self._make_outcome(
                f"SZ.00010{i}", "SELL", "2024-06-26T00:00:00", correct=i >= 4
            )
            enrichments[aid] = {"conclusion": "反对", "confidence": "低"}
        self._write_outcomes(outcomes)
        self._write_enrichments(enrichments)
        report = self._report()
        self.assertAlmostEqual(report["enriched_hit_rate"]["rate"], 0.6)
        self.assertAlmostEqual(report["veto_avoid_rate"]["rate"], 0.8)
        self.assertAlmostEqual(report["confidence_calibration"]["高"]["rate"], 0.6)
        self.assertIsNone(report["confidence_calibration"]["中"]["rate"])  # 无样本

    def test_empty_safe(self):
        report = self._report()  # 无 outcomes 文件
        self.assertIsNone(report["signal_hit_rate"]["rate"])
        self.assertEqual(report["total_outcomes"], 0)

    def test_by_symbol_breakdown(self):
        # 两标的：A 全命中、B 全未命中；按 (symbol, action) 分组独立统计
        outcomes = {}
        for i in range(3):
            outcomes[f"a{i}"] = self._make_outcome(
                "HK.00700", "BUY", f"2024-06-2{i}T00:00:00", True, ret=0.05
            )
        for i in range(3):
            outcomes[f"b{i}"] = self._make_outcome(
                "HK.06082", "BUY", f"2024-06-2{i}T00:00:00", False, ret=-0.10
            )
        self._write_outcomes(outcomes)
        by_symbol = self._report()["by_symbol"]
        # 小样本仍展示（min_sample=1），rate 不为 null
        self.assertEqual(by_symbol["HK.00700"]["BUY"]["hit_rate"]["rate"], 1.0)
        self.assertEqual(by_symbol["HK.06082"]["BUY"]["hit_rate"]["rate"], 0.0)
        self.assertAlmostEqual(
            by_symbol["HK.00700"]["BUY"]["avg_forward_return"]["avg"], 0.05
        )
        self.assertEqual(by_symbol["HK.00700"]["BUY"]["hit_rate"]["n"], 3)

    def test_by_symbol_dedupe(self):
        # 同 (symbol, action, bar_dt) 双 id → 该标的计一次
        outcomes = {
            "x0": self._make_outcome("HK.00700", "BUY", "2024-06-25T00:00:00", True),
            "x0b": self._make_outcome("HK.00700", "BUY", "2024-06-25T00:00:00", True),
        }
        self._write_outcomes(outcomes)
        by_symbol = self._report()["by_symbol"]
        self.assertEqual(by_symbol["HK.00700"]["BUY"]["hit_rate"]["n"], 1)


class TestDecoupling(_EvalsFileCase):

    def test_backfill_failure_does_not_touch_alerts(self):
        self._write_alert("buy1", "SH.600000", "BUY", "2024-06-25T00:00:00", 10.2)
        before = self.alerts_path.read_bytes()

        def always_fail(symbol, anchor_dt, now):
            raise RuntimeError("boom")

        summary = evals.backfill(
            now=datetime(2024, 7, 5), config=_EVALS_CONFIG,
            alerts_path=self.alerts_path, outcomes_path=self.outcomes_path,
            fetch_closes_fn=always_fail,
        )
        self.assertIn("buy1", summary["errors"])
        self.assertEqual(self.alerts_path.read_bytes(), before)  # 只读，未改
        self.assertFalse(self.outcomes_path.exists())


class TestRegistryWiring(unittest.TestCase):

    def test_evals_job_present_when_enabled(self):
        jobs = registry.build_jobs(_EVALS_CONFIG)
        evals_jobs = [j for j in jobs if j["name"] == registry.EVALS_JOB_NAME]
        self.assertEqual(len(evals_jobs), 1)
        self.assertIn("decidra.strategy.evals backfill", evals_jobs[0]["command"])

    def test_evals_job_absent_when_disabled(self):
        config = {"evals": {"enabled": False, "horizon_days": 5,
                            "report_window": 90, "schedule": "0 22 * * *"}}
        jobs = registry.build_jobs(config)
        self.assertNotIn(
            registry.EVALS_JOB_NAME, [j["name"] for j in jobs]
        )


class TestConfigNormalize(unittest.TestCase):

    def test_defaults(self):
        cfg = config_mod.normalize_evals_config({})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["horizon_days"], 5)
        self.assertEqual(cfg["report_window"], 90)

    def test_reject_invalid(self):
        for bad in [{"horizon_days": 0}, {"horizon_days": True},
                    {"report_window": -1}, {"schedule": "  "},
                    {"enabled": "yes"}]:
            with self.assertRaises(ValueError):
                config_mod.normalize_evals_config(bad)


class TestDisplaySummary(unittest.TestCase):

    def test_null_shows_dash(self):
        from decidra.strategy.display import format_evals_summary_lines

        report = {
            "window_days": 90, "horizon_days": 5,
            "signal_hit_rate": {"rate": 0.62, "n": 21},
            "avg_forward_return": {"BUY": {"avg": 0.012, "n": 8},
                                   "SELL": {"avg": None, "n": 2}},
            "enriched_hit_rate": {"rate": None, "n": 2},
            "veto_avoid_rate": {"rate": None, "n": 1},
            "confidence_calibration": {"高": {"rate": None, "n": 0},
                                       "中": {"rate": 0.58, "n": 12},
                                       "低": {"rate": None, "n": 3}},
        }
        lines = format_evals_summary_lines(report)
        self.assertEqual(len(lines), 2)
        text = "\n".join(lines)
        self.assertIn("62%", text)
        self.assertIn("—", text)  # null 度量显示破折号

    def test_symbol_line_best_worst(self):
        from decidra.strategy.display import format_evals_symbol_line

        report = {
            "by_symbol": {
                "HK.00100": {"SELL": {"avg_forward_return": {"avg": 0.20, "n": 13}}},
                "HK.07688": {"BUY": {"avg_forward_return": {"avg": -0.19, "n": 5}}},
            }
        }
        line = format_evals_symbol_line(report)
        self.assertIsNotNone(line)
        self.assertIn("HK.00100", line)  # 最佳
        self.assertIn("HK.07688", line)  # 最差

    def test_symbol_line_skips_small_sample(self):
        from decidra.strategy.display import format_evals_symbol_line

        # 均 n<3，达阈值分组不足 2 个 → 不展示
        report = {
            "by_symbol": {
                "HK.00700": {"BUY": {"avg_forward_return": {"avg": 0.05, "n": 2}}},
            }
        }
        self.assertIsNone(format_evals_symbol_line(report))


@unittest.skipUnless(
    os.environ.get("DECIDRA_RUN_NET_TESTS") == "1",
    "gated：需真实数据源，DECIDRA_RUN_NET_TESTS=1 开启",
)
class TestRealBackfill(unittest.TestCase):

    def test_backfill_real_alerts(self):
        # 用真实告警文件回填（若有历史告警），只验证不崩、结构正确
        summary = evals.backfill(now=datetime.now())
        self.assertIn("priced", summary)
        self.assertIn("pending", summary)
        report = evals.report()
        self.assertIn("signal_hit_rate", report)


if __name__ == "__main__":
    unittest.main()
