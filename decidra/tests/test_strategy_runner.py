"""策略模块（config / alerts / czsc_resonance / runner）测试。

无 mock：合成数据注入替换数据源，文件走临时目录，gated 用例用真实富途取数。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from decidra.strategy import czsc_resonance
from decidra.strategy.alerts import Alert, DedupeState, append_alerts, read_new_alerts
from decidra.strategy.config import DEFAULT_CONFIG, load_config
from decidra.strategy.runner import install_cron, run_scan


def _synthetic_daily_df(n: int = 600):
    """仅含工作日、带波段的标准化日线 DataFrame（确定性，无网络）。"""
    import pandas as pd

    dts = pd.bdate_range("2023-01-02", periods=n)
    rows = []
    for i, dt in enumerate(dts):
        price = 100 + 15 * math.sin(i / 8.0) + 6 * math.sin(i / 3.0)
        rows.append({
            "symbol": "TEST", "dt": dt.to_pydatetime(),
            "open": price - 0.5, "close": price + 0.5,
            "high": price + 1.5, "low": price - 1.5,
            "vol": 10000.0 + i, "amount": (10000.0 + i) * (price + 0.5),
        })
    return pd.DataFrame(rows)


class TestStrategyConfig(unittest.TestCase):
    def test_create_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = load_config(path)
            self.assertEqual(config, DEFAULT_CONFIG)
            self.assertTrue(path.exists(), "首次加载应写入默认配置文件")

    def test_merge_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"watchlist": ["HK.09988"]}), encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config["watchlist"], ["HK.09988"])
            self.assertIn("cron", config, "缺失键应由默认配置补齐")

    def test_corrupt_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not valid json", encoding="utf-8")
            self.assertEqual(load_config(path), DEFAULT_CONFIG)
            path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
            self.assertEqual(load_config(path), DEFAULT_CONFIG, "非字典应回退默认")


class TestAlerts(unittest.TestCase):
    def _alert(self, action: str = "BUY") -> Alert:
        return Alert(dt=datetime.now().isoformat(), symbol="TEST", strategy="s",
                     action=action, reason="r", bar_dt="2026-07-13T00:00:00")

    def test_append_and_incremental_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.jsonl"
            alerts, offset = read_new_alerts(0, path)
            self.assertEqual((alerts, offset), ([], 0))

            append_alerts([self._alert("BUY")], path)
            alerts, offset = read_new_alerts(0, path)
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["action"], "BUY")

            # 无新增时偏移不变
            again, offset2 = read_new_alerts(offset, path)
            self.assertEqual(again, [])
            self.assertEqual(offset2, offset)

            append_alerts([self._alert("SELL")], path)
            new, _ = read_new_alerts(offset, path)
            self.assertEqual([a["action"] for a in new], ["SELL"])

    def test_partial_line_not_skipped(self):
        """写了一半的行不应被跳过：偏移停在最后完整行尾，补全后可读到。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.jsonl"
            append_alerts([self._alert("BUY")], path)
            alerts, offset = read_new_alerts(0, path)
            self.assertEqual(len(alerts), 1)

            # 模拟并发写入者只写了半行
            with path.open("a", encoding="utf-8") as fh:
                fh.write('{"action": "SE')
            alerts, offset2 = read_new_alerts(offset, path)
            self.assertEqual(alerts, [], "半行不应产出记录")
            self.assertEqual(offset2, offset, "偏移不应越过半行")

            # 写入者补全该行
            with path.open("a", encoding="utf-8") as fh:
                fh.write('LL", "symbol": "X"}\n')
            alerts, _ = read_new_alerts(offset2, path)
            self.assertEqual([a["action"] for a in alerts], ["SELL"], "补全后应完整读到")

    def test_dedupe_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = DedupeState(path)
            self.assertTrue(state.should_fire("TEST", "s", "BUY", "bar1"))
            state.mark("TEST", "s", "BUY", "bar1")
            state.save()

            reloaded = DedupeState(path)
            self.assertFalse(reloaded.should_fire("TEST", "s", "BUY", "bar1"), "同一K线应去重")
            self.assertTrue(reloaded.should_fire("TEST", "s", "BUY", "bar2"), "新K线应放行")
            self.assertTrue(reloaded.should_fire("TEST", "s", "SELL", "bar1"), "不同动作独立去重")

    def test_dedupe_unconfirmed_upgrade_refires(self):
        """未确认告警后同一K线转为已确认：视为新事件放行一次。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = DedupeState(path)
            state.mark("TEST", "s", "BUY", "bar1", confirmed=False)
            state.save()

            reloaded = DedupeState(path)
            self.assertFalse(
                reloaded.should_fire("TEST", "s", "BUY", "bar1", confirmed=False),
                "同一K线重复的未确认告警应去重")
            self.assertTrue(
                reloaded.should_fire("TEST", "s", "BUY", "bar1", confirmed=True),
                "未确认→已确认应放行（转正）")

            reloaded.mark("TEST", "s", "BUY", "bar1", confirmed=True)
            self.assertFalse(
                reloaded.should_fire("TEST", "s", "BUY", "bar1", confirmed=True),
                "转正后再次已确认应去重")
            self.assertFalse(
                reloaded.should_fire("TEST", "s", "BUY", "bar1", confirmed=False),
                "已确认后降级不应再告警")

    def test_dedupe_legacy_entry_treated_confirmed(self):
        """旧状态文件（纯 bar_dt 值）按已确认解释。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"TEST|s|BUY": "bar1"}), encoding="utf-8")
            state = DedupeState(path)
            self.assertFalse(state.should_fire("TEST", "s", "BUY", "bar1", confirmed=True))
            self.assertFalse(state.should_fire("TEST", "s", "BUY", "bar1", confirmed=False))


class TestDecide(unittest.TestCase):
    """czsc_resonance 纯决策函数的规则分支。"""

    def test_cross_resonance(self):
        self.assertEqual(czsc_resonance.decide({}, None, "看多_任意_任意_0"),
                         [("BUY", "周日线中枢共振看多", [])])
        self.assertEqual(czsc_resonance.decide({}, None, "看空_任意_任意_0"),
                         [("SELL", "周日线中枢共振看空", [])])

    def test_weekly_confirmed_no_caveat(self):
        fired = {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向上", "其他")
        self.assertEqual(len(decisions), 1)
        action, reason, caveats = decisions[0]
        self.assertEqual(action, "BUY")
        self.assertIn("周线末笔向上", reason)
        self.assertEqual(caveats, [], "周线同向确认不应有警示")

    def test_weekly_opposed_fires_with_caveat(self):
        """周线反向不再拦截：照常告警但带红字警示。"""
        fired = {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向下", "其他")
        self.assertEqual(len(decisions), 1)
        action, reason, caveats = decisions[0]
        self.assertEqual(action, "BUY")
        self.assertIn("三买", reason)
        self.assertNotIn("周线末笔", reason, "未确认时理由不应含周线确认语")
        self.assertEqual(
            caveats,
            [czsc_resonance.CAVEAT_WEEKLY_OPPOSED.format(direction="向下")])

    def test_weekly_none_fires_with_caveat(self):
        """周线笔未形成（次新股）不再拦截：照常告警但带红字警示。"""
        fired = {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"}
        decisions = czsc_resonance.decide(fired, None, "其他")
        self.assertEqual(len(decisions), 1)
        action, _, caveats = decisions[0]
        self.assertEqual(action, "BUY")
        self.assertEqual(caveats, [czsc_resonance.CAVEAT_WEEKLY_NO_BI])

    def test_sell_branch(self):
        fired = {"日线_D1_一卖V221126": "一卖_5笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向下", "其他")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0][0], "SELL")
        self.assertEqual(decisions[0][2], [])

    def test_same_action_reasons_merged(self):
        fired = {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向上", "看多_任意_任意_0")
        self.assertEqual(len(decisions), 1, "同向理由应合并为一条")
        self.assertIn("共振看多", decisions[0][1])
        self.assertIn("三买", decisions[0][1])

    def test_conflict_keeps_both_sides_with_caveat(self):
        """共振与日线信号方向冲突时双侧都告警，反向侧带共振警示。"""
        fired = {"日线_D1_一卖V221126": "一卖_5笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向下", "看多_任意_任意_0")
        self.assertEqual(len(decisions), 2, "冲突双侧都应保留")
        by_action = {action: (reason, caveats) for action, reason, caveats in decisions}
        self.assertIn("共振看多", by_action["BUY"][0])
        self.assertEqual(by_action["BUY"][1], [], "共振侧不应有共振警示")
        self.assertIn("一卖", by_action["SELL"][0])
        self.assertIn(
            czsc_resonance.CAVEAT_AGAINST_RESONANCE.format(side="看多"),
            by_action["SELL"][1])
        self.assertIn("周线末笔向下", by_action["SELL"][0], "周线同向确认语保留")

        fired = {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"}
        decisions = czsc_resonance.decide(fired, "向上", "看空_任意_任意_0")
        by_action = {action: (reason, caveats) for action, reason, caveats in decisions}
        self.assertIn(
            czsc_resonance.CAVEAT_AGAINST_RESONANCE.format(side="看空"),
            by_action["BUY"][1])

    def test_conflict_without_resonance_marks_both(self):
        """无共振方向时买卖信号并存：双侧都标注存在反向信号。"""
        fired = {
            "日线_D1_一买V221216": "一买_金叉_任意_0",
            "日线_D1_一卖V221126": "一卖_5笔_任意_0",
        }
        decisions = czsc_resonance.decide(fired, "向上", "其他")
        self.assertEqual(len(decisions), 2)
        for _, _, caveats in decisions:
            self.assertIn(czsc_resonance.CAVEAT_CONFLICT, caveats)

    def test_no_signal_no_decision(self):
        self.assertEqual(czsc_resonance.decide({}, "向上", "其他"), [])

    def test_classify_keyword_variants(self):
        """扩展信号的值词表：类一买/底背驰/颈线突破等按 v1 段关键词归类。"""
        buy_values = (
            "ABC式类一买_任意_任意_0",     # 九笔
            "类趋势一买_任意_任意_0",       # 九笔
            "ZG三买_任意_任意_0",           # 九笔
            "类三买A_任意_任意_0",          # 九笔
            "aAb式底背驰_任意_任意_0",      # 五笔
            "上颈线突破_任意_任意_0",       # 五笔（下跌五笔中的看多突破）
            "二买_任意_任意_0",             # second_bs_V240524
        )
        sell_values = (
            "A3B5C3式类一卖_任意_任意_0",
            "ZD三卖_任意_任意_0",
            "类趋势顶背驰_任意_任意_0",
            "下颈线突破_任意_任意_0",
        )
        for v in buy_values:
            self.assertEqual(czsc_resonance._classify(v), "BUY", v)
        for v in sell_values:
            self.assertEqual(czsc_resonance._classify(v), "SELL", v)

    def test_classify_tas_values(self):
        """tas 信号值词表：一买一卖/二买二卖/底顶背驰/买点卖点。"""
        self.assertEqual(czsc_resonance._classify("一买_死叉_任意_0"), "BUY")
        self.assertEqual(czsc_resonance._classify("二卖_金叉_任意_0"), "SELL")
        self.assertEqual(czsc_resonance._classify("底背驰_第1次_任意_0"), "BUY")
        self.assertEqual(czsc_resonance._classify("买点_任意_任意_0"), "BUY")
        self.assertEqual(czsc_resonance._classify("卖点_任意_任意_0"), "SELL")

    def test_default_signals_all_resolvable(self):
        """默认信号集中的每个函数名都能在信号模块中解析到。"""
        for name in czsc_resonance._DEFAULT_SIGNALS:
            self.assertIsNotNone(
                czsc_resonance._resolve_signal(name), f"信号 {name} 无法解析"
            )
        self.assertIsNone(czsc_resonance._resolve_signal("no_such_signal"))

    def test_directionless_value_not_counted(self):
        """无方向的结构值（如七笔中枢完成）不参与触发。"""
        self.assertIsNone(czsc_resonance._classify("向上中枢完成_任意_任意_0"))
        fired = {"日线_D1七笔_形态V230620": "向上中枢完成_任意_任意_0"}
        self.assertEqual(czsc_resonance.decide(fired, "向上", "其他"), [])

    def test_new_signal_triggers_buy_with_weekly_up(self):
        fired = {"日线_D1九笔_形态V230621": "aAbcd式类一买_任意_任意_0"}
        decisions = czsc_resonance.decide(fired, "向上", "其他")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0][0], "BUY")
        self.assertIn("类一买", decisions[0][1])


class TestEvaluate(unittest.TestCase):
    def test_synthetic_df_smoke(self):
        alerts = czsc_resonance.evaluate("TEST", _synthetic_daily_df(600))
        self.assertIsInstance(alerts, list)
        for alert in alerts:
            self.assertIn(alert.action, ("BUY", "SELL"))
            self.assertTrue(alert.bar_dt)
            self.assertIn("weekly_direction", alert.snapshot)
            self.assertIn("cross_signal", alert.snapshot)

    def test_signals_param_overrides_signal_set(self):
        """params["signals"] 覆盖信号集：空列表时 snapshot 无日线信号。"""
        alerts_all = czsc_resonance.evaluate("TEST", _synthetic_daily_df(600))
        alerts_none = czsc_resonance.evaluate(
            "TEST", _synthetic_daily_df(600), params={"signals": []}
        )
        for alert in alerts_none:
            self.assertEqual(alert.snapshot["daily_fired"], {})
        # 两次评估的共振信号一致（signals 只影响日线信号集）
        if alerts_all and alerts_none:
            self.assertEqual(
                alerts_all[0].snapshot["cross_signal"],
                alerts_none[0].snapshot["cross_signal"],
            )


class TestRunScan(unittest.TestCase):
    def _config(self) -> dict:
        return {
            "watchlist": ["TEST"],
            "kline_days": 730,
            "strategies": [{"name": "czsc_resonance", "enabled": True, "params": {}}],
        }

    def test_scan_with_injected_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            alerts_path = Path(tmp) / "alerts.jsonl"
            state_path = Path(tmp) / "state.json"
            fetch = lambda symbol, days: _synthetic_daily_df(600)  # noqa: E731

            summary = run_scan(self._config(), fetch, alerts_path, state_path)
            self.assertEqual(summary["scanned"], 1)
            self.assertEqual(summary["errors"], {})

            # 第二轮：同一根 K 线应全部去重，不追加新告警
            summary2 = run_scan(self._config(), fetch, alerts_path, state_path)
            self.assertEqual(summary2["alerts"], 0)
            self.assertEqual(summary2["suppressed"], summary["alerts"])

    def test_unknown_strategy_reported(self):
        config = {"watchlist": ["TEST"],
                  "strategies": [{"name": "no_such_strategy", "enabled": True}]}
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_scan(config, lambda s, d: _synthetic_daily_df(300),
                               Path(tmp) / "a.jsonl", Path(tmp) / "s.json")
            self.assertIn("no_such_strategy", summary["errors"])

    def test_fetch_error_isolated(self):
        config = {"watchlist": ["BAD", "TEST"],
                  "strategies": [{"name": "czsc_resonance", "enabled": True}]}

        def fetch(symbol, days):
            if symbol == "BAD":
                raise ValueError("no data")
            return _synthetic_daily_df(300)

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_scan(config, fetch, Path(tmp) / "a.jsonl", Path(tmp) / "s.json")
            self.assertIn("BAD", summary["errors"])
            self.assertEqual(summary["scanned"], 2, "单只取数失败不应中断整轮扫描")

    def test_strategy_filter_scans_only_named(self):
        config = {
            "watchlist": ["TEST"],
            "strategies": [
                {"name": "czsc_resonance", "enabled": True},
                {"name": "no_such_strategy", "enabled": True},
            ],
        }
        fetch = lambda symbol, days: _synthetic_daily_df(600)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_scan(config, fetch, Path(tmp) / "a.jsonl", Path(tmp) / "s.json",
                               strategy="czsc_resonance")
            self.assertNotIn("no_such_strategy", summary["errors"],
                             "--strategy 过滤后不应触碰其他策略")

    def test_strategy_filter_unknown_returns_empty_scan(self):
        config = {"watchlist": ["TEST"],
                  "strategies": [{"name": "czsc_resonance", "enabled": True}]}
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_scan(config, lambda s, d: _synthetic_daily_df(300),
                               Path(tmp) / "a.jsonl", Path(tmp) / "s.json",
                               strategy="ghost")
            self.assertEqual(summary["scanned"], 0)
            self.assertIn("ghost", summary["errors"])


class TestInstallCron(unittest.TestCase):
    """cron job 同步（decidra.tasks 注册表：每个启用策略一个独立 job）。"""

    CONFIG = {
        "strategies": [
            {"name": "czsc_resonance", "enabled": True},
            {"name": "fast_strategy", "enabled": True, "schedule": "* * * * *"},
            {"name": "disabled_one", "enabled": False},
        ],
        "cron": {"schedule": "*/30 1-8 * * 1-5"},
        # 关掉 evals 单例，使本用例断言聚焦策略 job（evals 注册另见
        # test_strategy_evals.TestRegistryWiring）
        "evals": {"enabled": False},
    }

    def test_build_jobs_per_strategy_with_schedule_override(self):
        from decidra.tasks.registry import build_jobs

        jobs = build_jobs(self.CONFIG)
        by_name = {j["name"]: j for j in jobs}
        self.assertEqual(
            set(by_name),
            {"decidra_strategy_czsc_resonance", "decidra_strategy_fast_strategy"},
            "每个启用策略一个 job，禁用策略不注册",
        )
        self.assertEqual(
            by_name["decidra_strategy_czsc_resonance"]["schedule"], "*/30 1-8 * * 1-5",
            "未配置策略级 schedule 时回退顶层 cron.schedule",
        )
        self.assertEqual(
            by_name["decidra_strategy_fast_strategy"]["schedule"], "* * * * *",
            "策略级 schedule 覆盖顶层配置",
        )
        self.assertIn(
            "--strategy czsc_resonance",
            by_name["decidra_strategy_czsc_resonance"]["command"],
        )

    def test_sync_writes_jobs_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("OPENHARNESS_CONFIG_DIR")
            os.environ["OPENHARNESS_CONFIG_DIR"] = tmp
            try:
                from openharness.services.cron import upsert_cron_job

                # 旧单体 job、已禁用新闻 job、用户自有 job 并存
                upsert_cron_job({"name": "decidra_strategy_scan",
                                 "schedule": "*/5 * * * *", "command": "old"})
                upsert_cron_job({"name": "decidra_news_radar",
                                 "schedule": "*/3 * * * *", "command": "stale"})
                upsert_cron_job({"name": "user_own_job",
                                 "schedule": "0 0 * * *", "command": "keep"})
                upsert_cron_job({"name": "decidra_backup",
                                 "schedule": "0 1 * * *", "command": "keep"})

                result = install_cron(self.CONFIG)

                self.assertEqual(
                    set(result["removed"]),
                    {"decidra_strategy_scan", "decidra_news_radar"},
                    "清理策略前缀、遗留单体与已禁用新闻 job",
                )
                jobs = json.loads((Path(tmp) / "data" / "cron_jobs.json").read_text(encoding="utf-8"))
                names = {j["name"] for j in jobs}
                self.assertIn("decidra_strategy_czsc_resonance", names)
                self.assertIn("decidra_strategy_fast_strategy", names)
                self.assertIn("user_own_job", names, "非 decidra_ 前缀 job 不受影响")
                self.assertIn("decidra_backup", names,
                              "decidra_ 前缀但非策略前缀的用户 job 不得被删除")
                self.assertNotIn("decidra_strategy_scan", names)
                self.assertNotIn("decidra_news_radar", names)
            finally:
                if old_env is None:
                    os.environ.pop("OPENHARNESS_CONFIG_DIR", None)
                else:
                    os.environ["OPENHARNESS_CONFIG_DIR"] = old_env

    def test_invalid_strategy_name_rejected(self):
        from decidra.tasks.registry import build_jobs

        for bad_name in ("my strategy", "x;rm", "a|b", "czsc\n"):
            with self.assertRaises(ValueError, msg=f"策略名 {bad_name!r} 应被拒绝"):
                build_jobs({"strategies": [{"name": bad_name, "enabled": True}]})

    def test_invalid_schedule_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("OPENHARNESS_CONFIG_DIR")
            os.environ["OPENHARNESS_CONFIG_DIR"] = tmp
            try:
                with self.assertRaises(ValueError):
                    install_cron({
                        "strategies": [{"name": "bad", "schedule": "not-a-cron"}],
                    })
            finally:
                if old_env is None:
                    os.environ.pop("OPENHARNESS_CONFIG_DIR", None)
                else:
                    os.environ["OPENHARNESS_CONFIG_DIR"] = old_env


class TestDisplay(unittest.TestCase):
    """终端展示格式（Rich markup 纯函数）。"""

    def _alert_dict(self, action: str = "SELL") -> dict:
        from dataclasses import asdict
        return asdict(Alert(
            dt="2026-07-13T20:36:03", symbol="HK.00700", strategy="czsc_resonance",
            action=action, reason="周日线中枢共振看空", bar_dt="2026-07-13T00:00:00",
            snapshot={"last_close": 457.6, "daily_fired": {"日线_D1_三买辅助V230228": "三买_10笔_任意_0"},
                      "weekly_direction": "向下", "cross_signal": "看空_任意_任意_0"},
        ))

    def test_format_alert_fields(self):
        from decidra.strategy.display import format_alert

        text = format_alert(self._alert_dict("SELL"))
        for expected in ("▼ SELL", "HK.00700", "@457.6", "周日线中枢共振看空",
                         "周线 向下", "共振 看空", "三买", "#"):
            self.assertIn(expected, text)
        self.assertIn("▲ BUY", format_alert(self._alert_dict("BUY")))

    def test_format_alert_with_enrichment(self):
        from decidra.strategy.display import format_alert

        text = format_alert(self._alert_dict(), {"conclusion": "支持", "confidence": "高",
                                                 "summary": "结构复核成立"})
        self.assertIn("研判:", text)
        self.assertIn("[green]支持[/]", text)
        self.assertIn("结构复核成立", text)

    def test_format_alert_tolerates_legacy_record(self):
        from decidra.strategy.display import format_alert

        # 旧记录无 id/snapshot/caveats 字段也应可渲染
        text = format_alert({"symbol": "X", "action": "BUY", "reason": "r",
                             "dt": "2026-07-13T00:00:00", "bar_dt": ""})
        self.assertIn("▲ BUY", text)

    def test_format_alert_renders_caveats_red(self):
        from decidra.strategy.display import format_alert

        alert = self._alert_dict("BUY")
        alert["caveats"] = ["周线笔未形成，方向未获确认"]
        text = format_alert(alert)
        self.assertIn("[bold red]⚠ 周线笔未形成，方向未获确认[/]", text)
        # 无 caveats 时不出现警示行
        self.assertNotIn("⚠", format_alert(self._alert_dict("BUY")))

    def test_format_alert_includes_stock_name(self):
        """basicinfo 缓存命中时告警标题显示"代码 名称"。"""
        from decidra.strategy import display

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "stock_basicinfo_cache.json"
            cache_path.write_text(json.dumps({
                "data": {"HK.00700": {"code": "HK.00700", "name": "腾讯控股"}}
            }), encoding="utf-8")
            original = display.BASICINFO_CACHE_PATH
            display.BASICINFO_CACHE_PATH = cache_path
            display._names_cache = (None, {})
            try:
                text = display.format_alert(self._alert_dict("SELL"))
                self.assertIn("HK.00700 腾讯控股", text)
                options_line = display._symbol_display("HK.00700")
                self.assertEqual(options_line, "HK.00700 腾讯控股")
            finally:
                display.BASICINFO_CACHE_PATH = original
                display._names_cache = (None, {})

    def test_format_alert_without_name_cache_degrades(self):
        """缓存文件不存在或未命中时只显示代码，不报错。"""
        from decidra.strategy import display

        with tempfile.TemporaryDirectory() as tmp:
            original = display.BASICINFO_CACHE_PATH
            display.BASICINFO_CACHE_PATH = Path(tmp) / "missing.json"
            display._names_cache = (None, {})
            try:
                text = display.format_alert(self._alert_dict("SELL"))
                self.assertIn("[bold]HK.00700[/]", text, "无名称时代码后不应有多余空格")
            finally:
                display.BASICINFO_CACHE_PATH = original
                display._names_cache = (None, {})

    def test_build_alert_options(self):
        from decidra.strategy.alerts import save_enrichment
        from decidra.strategy.display import build_alert_options

        with tempfile.TemporaryDirectory() as tmp:
            alerts_path = Path(tmp) / "a.jsonl"
            enrich_path = Path(tmp) / "enrich.json"
            old = Alert(dt="2026-07-12T10:00:00", symbol="HK.00700", strategy="s",
                        action="SELL", reason="r", bar_dt="2026-07-11T00:00:00",
                        snapshot={"last_close": 457.6})
            new = Alert(dt="2026-07-13T10:00:00", symbol="HK.09988", strategy="s",
                        action="BUY", reason="r", bar_dt="2026-07-12T00:00:00")
            append_alerts([old, new], alerts_path)
            save_enrichment(old.id, {"conclusion": "支持", "confidence": "高"}, enrich_path)

            options = build_alert_options(10, alerts_path, enrich_path)
            self.assertEqual([oid for oid, _ in options], [new.id, old.id], "应新→旧排序")
            self.assertIn("未研判", options[0][1])
            self.assertIn("▲ BUY", options[0][1])
            self.assertIn("已研判·支持", options[1][1])
            self.assertIn("@457.6", options[1][1])

    def test_build_alert_options_skips_legacy_without_id(self):
        from decidra.strategy.display import build_alert_options

        with tempfile.TemporaryDirectory() as tmp:
            alerts_path = Path(tmp) / "a.jsonl"
            alerts_path.write_text(
                json.dumps({"symbol": "X", "action": "BUY"}) + "\n", encoding="utf-8")
            self.assertEqual(
                build_alert_options(10, alerts_path, Path(tmp) / "e.json"), [])

    def test_build_enrich_prompt(self):
        from decidra.strategy.display import build_enrich_prompt

        alert = self._alert_dict("SELL")
        prompt = build_enrich_prompt(alert)
        for expected in (f"#{alert['id']}", "HK.00700", "SELL", "strategy_alerts_list",
                         "czsc_multi_level_analysis", "strategy_alert_enrich",
                         "支持/反对/观望"):
            self.assertIn(expected, prompt)

    def test_startup_lines_without_job(self):
        from decidra.strategy.display import build_startup_lines

        with tempfile.TemporaryDirectory() as tmp:
            lines = build_startup_lines(
                config={"watchlist": ["HK.00700"],
                        "strategies": [{"name": "czsc_resonance", "enabled": True}]},
                alerts_path=Path(tmp) / "a.jsonl",
                jobs_path=Path(tmp) / "jobs.json",
                history_path=Path(tmp) / "hist.jsonl",
            )
            text = "\n".join(lines)
            self.assertIn("未注册", text)
            self.assertIn("暂无历史告警", text)

    def test_startup_lines_with_job_history_and_alerts(self):
        from decidra.strategy.display import build_startup_lines

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = Path(tmp) / "jobs.json"
            history_path = Path(tmp) / "hist.jsonl"
            alerts_path = Path(tmp) / "a.jsonl"
            jobs_path.write_text(json.dumps([{
                "name": "decidra_strategy_czsc_resonance", "schedule": "*/5 * * * *",
                "enabled": True, "next_run": "2026-07-13T12:45:00+00:00",
            }]), encoding="utf-8")
            history_path.write_text(json.dumps({
                "name": "decidra_strategy_czsc_resonance", "status": "success",
                "started_at": "2026-07-13T12:45:01+00:00",
            }) + "\n", encoding="utf-8")
            append_alerts([Alert(dt="2026-07-13T12:45:02", symbol="HK.00700",
                                 strategy="s", action="SELL", reason="r",
                                 bar_dt="2026-07-13T00:00:00")], alerts_path)

            lines = build_startup_lines(
                config={"watchlist": ["HK.00700"],
                        "strategies": [{"name": "czsc_resonance", "enabled": True}]},
                alerts_path=alerts_path, jobs_path=jobs_path, history_path=history_path,
                enrichments_path=Path(tmp) / "enrich.json",
            )
            text = "\n".join(lines)
            self.assertIn("czsc_resonance", text)
            self.assertIn("启用", text)
            self.assertIn("success", text)
            self.assertIn("最近告警 1 条", text)
            self.assertIn("▼ SELL", text)


class TestEnrichment(unittest.TestCase):
    """研判结论的存取与告警定位。"""

    def test_save_load_roundtrip_and_overwrite(self):
        from decidra.strategy.alerts import load_enrichments, save_enrichment

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "enrich.json"
            self.assertEqual(load_enrichments(path), {})
            save_enrichment("abc123", {"conclusion": "支持", "confidence": "高"}, path)
            save_enrichment("abc123", {"conclusion": "观望", "confidence": "中"}, path)
            data = load_enrichments(path)
            self.assertEqual(data["abc123"]["conclusion"], "观望", "重复研判应覆盖")

    def test_find_alert(self):
        from decidra.strategy.alerts import find_alert

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.jsonl"
            alert = Alert(dt="2026-07-13T00:00:00", symbol="HK.00700", strategy="s",
                          action="SELL", reason="r", bar_dt="b")
            append_alerts([alert], path)
            found = find_alert(alert.id, path)
            self.assertIsNotNone(found)
            self.assertEqual(found["symbol"], "HK.00700")
            self.assertIsNone(find_alert("nonexist", path))
            self.assertIsNone(find_alert("", path))


class TestStrategyServer(unittest.TestCase):
    """strategy MCP 服务器的工具行为（临时目录隔离真实路径）。"""

    def setUp(self):
        import decidra.strategy.alerts as alerts_mod
        self.alerts_mod = alerts_mod
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_alerts = alerts_mod.ALERTS_PATH
        self._orig_enrich = alerts_mod.ENRICHMENTS_PATH
        alerts_mod.ALERTS_PATH = Path(self._tmp.name) / "alerts.jsonl"
        alerts_mod.ENRICHMENTS_PATH = Path(self._tmp.name) / "enrichments.json"

    def tearDown(self):
        self.alerts_mod.ALERTS_PATH = self._orig_alerts
        self.alerts_mod.ENRICHMENTS_PATH = self._orig_enrich
        self._tmp.cleanup()

    def _call(self, tool: str, args: dict) -> dict:
        import asyncio
        from decidra.mcp_server.strategy_server import build_server

        srv = build_server()
        res = asyncio.new_event_loop().run_until_complete(srv.call_tool(tool, args))
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    def _seed_alert(self) -> Alert:
        alert = Alert(dt="2026-07-13T12:45:02", symbol="HK.00700", strategy="czsc_resonance",
                      action="SELL", reason="周日线中枢共振看空", bar_dt="2026-07-13T00:00:00",
                      snapshot={"last_close": 457.6})
        append_alerts([alert], self.alerts_mod.ALERTS_PATH)
        return alert

    def test_list_and_enrich_flow(self):
        alert = self._seed_alert()

        listed = self._call("strategy_alerts_list", {"n": 10})
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["data"]["count"], 1)
        self.assertFalse(listed["data"]["alerts"][0]["enriched"])

        enriched = self._call("strategy_alert_enrich", {
            "alert_id": f"#{alert.id}", "conclusion": "支持",
            "summary": "周线结构复核成立", "confidence": "高"})
        self.assertTrue(enriched["ok"], f"研判写回失败: {enriched}")
        self.assertEqual(enriched["data"]["alert_id"], alert.id, "# 前缀应被剥离")

        listed2 = self._call("strategy_alerts_list", {"n": 10})
        item = listed2["data"]["alerts"][0]
        self.assertTrue(item["enriched"])
        self.assertEqual(item["enrichment"]["conclusion"], "支持")

    def test_enrich_validation(self):
        alert = self._seed_alert()
        bad_conclusion = self._call("strategy_alert_enrich", {
            "alert_id": alert.id, "conclusion": "买爆", "summary": "s"})
        self.assertFalse(bad_conclusion["ok"])

        bad_id = self._call("strategy_alert_enrich", {
            "alert_id": "nonexist", "conclusion": "支持", "summary": "s"})
        self.assertFalse(bad_id["ok"])
        self.assertIn("未找到", bad_id["error"])

    def test_register_includes_strategy(self):
        from decidra.mcp_server import register

        self.assertIn("strategy", register._desired_servers())


class TestReadRecentAlerts(unittest.TestCase):
    def test_tail_semantics(self):
        from decidra.strategy.alerts import read_recent_alerts

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.jsonl"
            self.assertEqual(read_recent_alerts(5, path), [])
            for i in range(8):
                append_alerts([Alert(dt=f"2026-07-13T00:00:0{i}", symbol=f"S{i}",
                                     strategy="s", action="BUY", reason="r",
                                     bar_dt="b")], path)
            recent = read_recent_alerts(3, path)
            self.assertEqual([a["symbol"] for a in recent], ["S5", "S6", "S7"])
            # n 大于总条数时返回全部
            self.assertEqual(len(read_recent_alerts(99, path)), 8)

    def test_tail_across_chunks(self):
        """尾部块读取跨块回退时记录应完整（用超过块大小的 payload 触发多次回退）。"""
        import decidra.strategy.alerts as alerts_mod

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.jsonl"
            big_reason = "x" * 300
            for i in range(20):
                append_alerts([Alert(dt=f"2026-07-13T00:00:{i:02d}", symbol=f"S{i}",
                                     strategy="s", action="BUY", reason=big_reason,
                                     bar_dt="b")], path)
            orig_chunk = alerts_mod._TAIL_CHUNK_BYTES
            alerts_mod._TAIL_CHUNK_BYTES = 256  # 强制多次回退
            try:
                recent = alerts_mod.read_recent_alerts(5, path)
            finally:
                alerts_mod._TAIL_CHUNK_BYTES = orig_chunk
            self.assertEqual([a["symbol"] for a in recent],
                             ["S15", "S16", "S17", "S18", "S19"])
            self.assertTrue(all(a["reason"] == big_reason for a in recent))


def _futu_opend_ready() -> bool:
    """FutuOpenD 网关是否在线（决定是否跳过富途真实数据测试）。"""
    import socket
    try:
        socket.create_connection(("127.0.0.1", 11111), timeout=2).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(_futu_opend_ready(), "需 FutuOpenD 网关在线")
class TestStrategyFutuIntegration(unittest.TestCase):
    """真实富途取数 → 共振策略评估 端到端，gated。"""

    def test_real_futu_evaluate(self):
        from decidra.modules.futu_market import FutuMarket
        from decidra.strategy.runner import fetch_daily_df

        fm = FutuMarket()
        fm.open()
        try:
            df = fetch_daily_df(fm, "HK.00700", 730)
        finally:
            fm.close()
        self.assertGreater(len(df), 300)

        alerts = czsc_resonance.evaluate("HK.00700", df)
        self.assertIsInstance(alerts, list)
        for alert in alerts:
            self.assertIn(alert.action, ("BUY", "SELL"))
            self.assertTrue(alert.reason)


if __name__ == "__main__":
    unittest.main()
