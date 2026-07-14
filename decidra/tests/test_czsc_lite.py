"""czsc_lite（fork 的缠论信号分析核心）与 czsc MCP 服务器单元测试。

背景：
decidra/mcp_server/czsc_lite 是从 czsc(v0.9.69) fork 的缠论信号分析最小闭包，talib
被本地纯 numpy ta 实现替代，仅依赖 numpy/pandas/scikit-learn（均已装），零重依赖。
czsc_server 以 MCP 工具暴露缠论分析给终端 agent，数据源用 yfinance。

确定性用例（无网络、不 mock）：用合成 K 线构建 CZSC、算分型/笔、跑缠论信号、
服务器工具注册。集成用例（需网络）：yfinance 取真实数据做缠论分析，gated。
"""
import json
import math
import unittest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

src_path = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))

from decidra.mcp_server.czsc_lite import CZSC, RawBar, Freq
from decidra.mcp_server.czsc_lite import signals_cxt
from decidra.mcp_server.czsc_server import build_server
from decidra.mcp_server import register as mcp_register


def _synthetic_bars(n: int = 250) -> list:
    """生成有明显波段的合成日线，使分型/笔能形成（确定性，无网络）。"""
    bars = []
    base = datetime(2024, 1, 1)
    for i in range(n):
        # 多个正弦叠加制造波段
        price = 100 + 15 * math.sin(i / 8.0) + 6 * math.sin(i / 3.0)
        high = price + 1.5
        low = price - 1.5
        open_ = price - 0.5
        close = price + 0.5
        bars.append(RawBar(
            symbol="TEST", id=i, dt=base + timedelta(days=i), freq=Freq.D,
            open=open_, close=close, high=high, low=low, vol=10000 + i, amount=(10000 + i) * close,
        ))
    return bars


class TestCzscLiteCore(unittest.TestCase):
    """验证缠论核心：CZSC 构建、分型/笔、信号计算（零重依赖）。"""

    @classmethod
    def setUpClass(cls):
        cls.c = CZSC(_synthetic_bars(250))

    def test_czsc_builds_fx_and_bi(self):
        """合成波段应产生分型与笔。"""
        self.assertGreater(len(self.c.bars_raw), 200)
        self.assertGreater(len(self.c.fx_list), 0, "未产生分型")
        self.assertGreater(len(self.c.bi_list), 0, "未产生笔")

    def test_signal_returns_ordered_dict_with_key_format(self):
        """缠论信号应返回 OrderedDict，键为 频率_位置_名称 格式。"""
        sig = signals_cxt.cxt_bi_status_V230101(self.c)
        self.assertTrue(sig, "信号为空")
        key = list(sig.keys())[0]
        self.assertIn("日线", key)  # 频率
        self.assertGreaterEqual(len(key.split("_")), 3)

    def test_multiple_signals_compute_without_talib(self):
        """多个缠论信号应能在无 talib 环境下计算。"""
        names = ["cxt_bi_end_V230618", "cxt_three_bi_V230618",
                 "cxt_third_buy_V230228", "cxt_bi_trend_V230824"]
        for name in names:
            fn = getattr(signals_cxt, name)
            sig = dict(fn(self.c))
            self.assertEqual(len(sig), 1, f"{name} 应返回单个信号")

    def test_all_curated_signals_resolve_and_wellformed(self):
        """每个精选信号名都应解析为函数，且 dict(fn(c)) 返回单个格式合法的键。

        czsc_chan_analysis 对缺失/报错的信号是静默跳过的，若某精选名拼错会悄无声息
        地不生效。此测试遍历 _CURATED_SIGNALS 兜住这类回归。
        """
        from decidra.mcp_server.czsc_server import _CURATED_SIGNALS
        self.assertEqual(len(_CURATED_SIGNALS), len(set(_CURATED_SIGNALS)), "精选信号有重复")
        for name in _CURATED_SIGNALS:
            fn = getattr(signals_cxt, name, None)
            self.assertIsNotNone(fn, f"精选信号 {name} 在 signals_cxt 中不存在")
            sig = dict(fn(self.c))
            self.assertEqual(len(sig), 1, f"{name} 应返回单个信号")
            key = list(sig.keys())[0]
            self.assertGreaterEqual(len(key.split("_")), 3, f"{name} 键格式异常: {key}")
            self.assertIn("日线", key, f"{name} 键应含频率段: {key}")

    def test_no_heavy_deps_in_clean_subprocess(self):
        """纯净子进程导入 czsc_lite + 跑信号，不应引入 talib/streamlit 等重依赖。

        用子进程隔离，避免同进程被其它测试的 import 污染 sys.modules。
        """
        import subprocess
        code = "\n".join([
            "import sys, math",
            "from datetime import datetime, timedelta",
            "from decidra.mcp_server.czsc_lite import CZSC, RawBar, Freq, signals_cxt",
            "bars=[RawBar(symbol='T',id=i,dt=datetime(2024,1,1)+timedelta(days=i),freq=Freq.D,"
            "open=100+15*math.sin(i/8),close=100.5+15*math.sin(i/8),high=102+15*math.sin(i/8),"
            "low=98+15*math.sin(i/8),vol=1000,amount=100000) for i in range(250)]",
            "c=CZSC(bars); signals_cxt.cxt_third_buy_V230228(c)",
            "heavy=[m for m in ('talib','streamlit','clickhouse_connect','oss2','matplotlib') if m in sys.modules]",
            "print('HEAVY:'+ ','.join(heavy))",
        ])
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60, cwd=str(src_path.parent),
        )
        self.assertEqual(r.returncode, 0, f"子进程失败: {r.stderr[-300:]}")
        heavy_line = [l for l in r.stdout.splitlines() if l.startswith("HEAVY:")][0]
        leaked = heavy_line.replace("HEAVY:", "").strip()
        self.assertEqual(leaked, "", f"czsc_lite 引入了重依赖: {leaked}")


class TestCzscServer(unittest.TestCase):
    """验证 czsc MCP 服务器构建与注册。"""

    def test_server_registers_tools(self):
        """服务器应注册缠论分析工具。"""
        srv = build_server()
        tools = asyncio.new_event_loop().run_until_complete(srv.list_tools())
        names = {t.name for t in tools}
        self.assertIn("czsc_chan_analysis", names)
        self.assertIn("czsc_list_signals", names)

    def test_list_signals_tool(self):
        """czsc_list_signals 应返回缠论信号清单。"""
        srv = build_server()
        res = asyncio.new_event_loop().run_until_complete(srv.call_tool("czsc_list_signals", {}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertTrue(data["ok"])
        self.assertGreater(data["data"]["count"], 10)

    def test_list_signals_count_matches_module(self):
        """czsc_list_signals 返回的信号数应与 signals_cxt 中 cxt_ 函数数一致。"""
        import inspect
        expected = sum(1 for n, _ in inspect.getmembers(signals_cxt, inspect.isfunction)
                       if n.startswith("cxt_"))
        srv = build_server()
        res = asyncio.new_event_loop().run_until_complete(srv.call_tool("czsc_list_signals", {}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertEqual(data["data"]["count"], expected)
        # 每条含 name/desc 字段
        for item in data["data"]["signals"]:
            self.assertTrue(item["name"].startswith("cxt_"))
            self.assertIn("desc", item)

    def test_freq_map_covers_all_levels(self):
        """_FREQ_MAP 应覆盖全部级别并映射到有效的 (czsc频率, yfinance interval)。"""
        from decidra.mcp_server.czsc_server import _FREQ_MAP
        for name in ["日线", "周线", "月线", "60分钟", "30分钟", "15分钟"]:
            self.assertIn(name, _FREQ_MAP)
            freq_val, interval = _FREQ_MAP[name]
            self.assertTrue(freq_val, f"{name} 频率值为空")
            self.assertTrue(interval, f"{name} interval 为空")

    def test_register_includes_czsc(self):
        """register_mcp_servers 应包含 czsc server。"""
        import tempfile
        orig = mcp_register.SETTINGS_PATH
        tmp = Path(tempfile.mkdtemp(prefix="test_czscreg_"))
        mcp_register.SETTINGS_PATH = tmp / "settings.json"
        try:
            mcp_register.register_mcp_servers()
            servers = json.loads(mcp_register.SETTINGS_PATH.read_text(encoding="utf-8"))["mcp_servers"]
            self.assertIn("czsc", servers)
            self.assertEqual(servers["czsc"]["args"], ["-m", "decidra.mcp_server.czsc_server"])
        finally:
            mcp_register.SETTINGS_PATH = orig


class TestCzscChanAnalysisTool(unittest.TestCase):
    """验证 czsc_chan_analysis 工具的信号收集/汇总逻辑（注入合成 CZSC，无网络）。"""

    def setUp(self):
        import decidra.mcp_server.czsc_server as cs
        self.cs = cs
        self._orig = cs._build_czsc
        # 用合成 bars 构建的真实 CZSC 替换网络取数（非 mock 库，替换数据源）
        cs._build_czsc = lambda symbol, period, freq_name: CZSC(_synthetic_bars(250))

    def tearDown(self):
        self.cs._build_czsc = self._orig

    def test_chan_analysis_returns_structure_and_signals(self):
        """应返回分型/笔结构汇总与触发信号，且为合法 JSON。"""
        srv = self.cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_chan_analysis", {"symbol": "TEST", "period": "1y", "freq": "日线"}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertTrue(data["ok"], f"分析失败: {data}")
        d = data["data"]
        self.assertEqual(d["symbol"], "TEST")
        self.assertGreater(d["bi_count"], 0)
        self.assertGreater(d["fx_count"], 0)
        self.assertIn("fired_signals", d)
        self.assertIsInstance(d["fired_signals"], dict)

    def test_freq_passed_through_to_builder(self):
        """freq/period 参数应原样透传给 _build_czsc（覆盖非日线路径的接线）。"""
        captured = {}

        def fake_build(symbol, period, freq_name):
            captured["symbol"] = symbol
            captured["period"] = period
            captured["freq"] = freq_name
            return CZSC(_synthetic_bars(250))

        self.cs._build_czsc = fake_build
        srv = self.cs.build_server()
        asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_chan_analysis", {"symbol": "0700.HK", "period": "6mo", "freq": "周线"}))
        self.assertEqual(captured["symbol"], "0700.HK")
        self.assertEqual(captured["period"], "6mo")
        self.assertEqual(captured["freq"], "周线")

    def test_params_forwarded_to_signals(self):
        """params 应以 kwargs 透传给每个精选信号（信号可据此定制 di/均线等）。"""
        captured = {}
        orig_fn = signals_cxt.cxt_first_buy_V221126

        def capturing(c, **kwargs):
            captured.update(kwargs)
            return orig_fn(c, **kwargs)

        signals_cxt.cxt_first_buy_V221126 = capturing
        try:
            srv = self.cs.build_server()
            asyncio.new_event_loop().run_until_complete(srv.call_tool(
                "czsc_chan_analysis",
                {"symbol": "TEST", "params": {"di": 3, "timeperiod": 21}}))
        finally:
            signals_cxt.cxt_first_buy_V221126 = orig_fn
        self.assertEqual(captured.get("di"), 3, "di 未透传给信号")
        self.assertEqual(captured.get("timeperiod"), 21, "timeperiod 未透传给信号")

    def test_params_none_uses_defaults(self):
        """不传 params 时应以默认参数运行（di 缺省），信号键含 D1。"""
        srv = self.cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_chan_analysis", {"symbol": "TEST"}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertTrue(data["ok"])
        # 默认 di=1，含 di 的信号键应出现 D1（合成数据上一/三类买卖点常触发）
        keys = " ".join(data["data"]["fired_signals"].keys())
        self.assertNotIn("D3", keys, "未传 params 不应出现 di=3 的键")

    def test_fired_signals_exclude_sentinel(self):
        """fired_signals 中不应包含以 '其他' 开头的未触发信号（哨兵过滤生效）。"""
        srv = self.cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_chan_analysis", {"symbol": "TEST", "period": "1y", "freq": "日线"}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertTrue(data["ok"], f"分析失败: {data}")
        for k, v in data["data"]["fired_signals"].items():
            self.assertFalse(str(v).startswith("其他"), f"未触发信号 {k}={v} 不应进入 fired_signals")

    def test_chan_analysis_handles_build_error(self):
        """取数/构建失败时应返回 ok=False 而非抛异常。"""
        self.cs._build_czsc = lambda *a, **k: (_ for _ in ()).throw(ValueError("no data"))
        srv = self.cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_chan_analysis", {"symbol": "BAD"}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertFalse(data["ok"])
        self.assertIn("no data", data["error"])


def _yfinance_network_ready() -> bool:
    """能否联网访问 yfinance 数据源（决定是否跳过真实集成测试）。"""
    import socket
    try:
        socket.create_connection(("query1.finance.yahoo.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(_yfinance_network_ready(), "需联网访问 yfinance")
class TestCzscChanAnalysisIntegration(unittest.TestCase):
    """czsc_chan_analysis 真实端到端（yfinance 取数 → CZSC → 精选信号），gated。

    czsc 工具在进程内运行（非 MCP 子进程），无 teardown 挂起风险，用普通 TestCase
    配合 asyncio.new_event_loop 即可，与本文件其它工具测试一致。
    """

    def _call(self, args: dict) -> dict:
        srv = build_server()
        res = asyncio.new_event_loop().run_until_complete(srv.call_tool("czsc_chan_analysis", args))
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    def test_real_yfinance_chan_analysis(self):
        """AAPL 日线 1y 真实取数应产出结构汇总与合法信号，无哨兵漏进。"""
        data = self._call({"symbol": "AAPL", "period": "1y", "freq": "日线"})
        self.assertTrue(data["ok"], f"分析失败: {data}")
        d = data["data"]
        self.assertGreater(d["bars"], 100, "日线 1y 应有足够 K 线")
        self.assertGreater(d["fx_count"], 0, "未产生分型")
        self.assertGreater(d["bi_count"], 0, "未产生笔")
        self.assertIn(d["last_bi_direction"], ("向上", "向下"))
        for k, v in d["fired_signals"].items():
            self.assertFalse(str(v).startswith("其他"), f"未触发信号 {k}={v} 不应进入")

    def test_real_yfinance_accepts_custom_params(self):
        """真实路径应接受 params 透传（di/均线）且不报错。

        参数是否真正传导到信号由确定性测试 test_params_forwarded_to_signals 证明；
        此处仅确认真实 yfinance 路径带 params 时端到端可用、结构合法。
        """
        data = self._call({"symbol": "AAPL", "period": "1y",
                           "params": {"di": 2, "ma_type": "EMA", "timeperiod": 21}})
        self.assertTrue(data["ok"], f"带 params 分析失败: {data}")
        self.assertIsInstance(data["data"]["fired_signals"], dict)
        self.assertGreater(data["data"]["bi_count"], 0)


def _synthetic_daily_df(n: int = 600):
    """生成仅含工作日、带波段的标准化日线 DataFrame（确定性，无网络）。"""
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


class TestBarResample(unittest.TestCase):
    """日线 → 周线/月线 重采样的聚合语义。"""

    def test_freq_end_date(self):
        from decidra.mcp_server.czsc_lite import freq_end_date

        # 2024-01-03 是周三，所在周周五为 2024-01-05；当月月末 2024-01-31
        self.assertEqual(freq_end_date("2024-01-03", Freq.W).strftime("%Y-%m-%d"), "2024-01-05")
        self.assertEqual(freq_end_date("2024-01-03", Freq.M).strftime("%Y-%m-%d"), "2024-01-31")
        self.assertEqual(freq_end_date("2024-12-15", Freq.M).strftime("%Y-%m-%d"), "2024-12-31")

    def test_freq_end_date_normalizes_intraday_time(self):
        """带收盘时刻的 datetime 应与同日午夜归到同一周期结束日。"""
        from decidra.mcp_server.czsc_lite import freq_end_date

        with_time = freq_end_date(datetime(2024, 1, 3, 15, 30), Freq.W)
        midnight = freq_end_date(datetime(2024, 1, 4, 0, 0), Freq.W)
        self.assertEqual(with_time, midnight, "同一周不同时刻应聚合到同一根周线")
        self.assertEqual(with_time.strftime("%Y-%m-%d %H:%M"), "2024-01-05 00:00")

    def test_weekly_aggregation(self):
        """3 个整周的日线应聚合为 3 根周线，OHLCV 语义正确。"""
        import pandas as pd
        from decidra.mcp_server.czsc_lite import resample_bars

        # 2024-01-01(周一) 起 15 个工作日 = 3 个整周
        df = _synthetic_daily_df(15)
        df["dt"] = list(pd.bdate_range("2024-01-01", periods=15).to_pydatetime())
        bars = resample_bars(df, Freq.W, raw_bars=True)
        self.assertEqual(len(bars), 3)
        w1 = bars[0]
        d1 = df.iloc[:5]
        self.assertEqual(w1.open, d1["open"].iloc[0])
        self.assertEqual(w1.close, d1["close"].iloc[-1])
        self.assertEqual(w1.high, d1["high"].max())
        self.assertEqual(w1.low, d1["low"].min())
        self.assertEqual(w1.vol, d1["vol"].sum())
        self.assertEqual(w1.freq, Freq.W)
        self.assertEqual(w1.dt.isoweekday(), 5, "周线 dt 应为周五")

    def test_drop_unfinished(self):
        """默认丢弃最后一根未完成 K 线；raw_bars=False 时返回含未完成周期的 DataFrame。"""
        import pandas as pd
        from decidra.mcp_server.czsc_lite import resample_bars

        # 16 个工作日 = 3 个整周 + 1 天（未完成周）
        df = _synthetic_daily_df(16)
        df["dt"] = list(pd.bdate_range("2024-01-01", periods=16).to_pydatetime())
        bars = resample_bars(df, Freq.W, raw_bars=True)
        self.assertEqual(len(bars), 3, "未完成周应被丢弃")
        bars_keep = resample_bars(df, Freq.W, raw_bars=True, drop_unfinished=False)
        self.assertEqual(len(bars_keep), 4)
        dfk = resample_bars(df, Freq.W, raw_bars=False)
        self.assertEqual(len(dfk), 4)

    def test_monthly_aggregation(self):
        from decidra.mcp_server.czsc_lite import resample_bars

        df = _synthetic_daily_df(600)
        bars = resample_bars(df, Freq.M, raw_bars=True)
        self.assertGreater(len(bars), 20, "600 个工作日应有 20+ 根月线")
        self.assertTrue(all(b.freq == Freq.M for b in bars))
        # 月线成交量总和应等于对应日线区间总和（抽查首根）
        first_month = df[df["dt"].apply(lambda x: (x.year, x.month)) == (2023, 1)]
        self.assertEqual(bars[0].vol, first_month["vol"].sum())

    def test_minute_freq_rejected(self):
        from decidra.mcp_server.czsc_lite import resample_bars

        df = _synthetic_daily_df(10)
        with self.assertRaises(AssertionError):
            resample_bars(df, Freq.F60, raw_bars=True)


class TestKlineQuality(unittest.TestCase):
    """K 线质量检查：干净数据零问题，脏数据可检出。"""

    def test_clean_df_no_issues(self):
        from decidra.mcp_server.czsc_lite import summarize_kline_quality

        self.assertEqual(summarize_kline_quality(_synthetic_daily_df(100)), [])

    def test_dirty_df_detected(self):
        import numpy as np
        from decidra.mcp_server.czsc_lite import summarize_kline_quality

        df = _synthetic_daily_df(50)
        df.loc[5, "high"] = df.loc[5, "open"] - 10  # high 低于 open
        df.loc[10, "close"] = -1.0                  # 负价格
        df.loc[15, "vol"] = np.nan                  # 缺失值
        df.loc[20, "dt"] = df.loc[19, "dt"]         # 重复时间
        issues = summarize_kline_quality(df)
        text = "\n".join(issues)
        self.assertIn("price_reasonableness", text)
        self.assertIn("missing_values", text)
        self.assertIn("datetime_order", text)

    def test_missing_column_raises(self):
        from decidra.mcp_server.czsc_lite import check_kline_quality

        df = _synthetic_daily_df(10).drop(columns=["amount"])
        with self.assertRaises(ValueError):
            check_kline_quality(df)


class TestZhongShuGongZhen(unittest.TestCase):
    """跨级别中枢共振信号的 key 格式与容错。"""

    def _cat(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            kas={"周线": CZSC(_synthetic_bars(250)), "日线": CZSC(_synthetic_bars(250))},
            symbol="TEST",
        )

    def test_key_format_and_legal_value(self):
        sig = dict(signals_cxt.cxt_zhong_shu_gong_zhen_V221221(self._cat(), freq1="周线", freq2="日线"))
        self.assertEqual(len(sig), 1)
        key = next(iter(sig))
        self.assertTrue(key.startswith("周线_日线_中枢共振V221221"))
        value = str(sig[key])
        self.assertTrue(value.startswith(("看多", "看空", "其他")), f"非法信号值: {value}")

    def test_missing_freq_returns_other(self):
        sig = dict(signals_cxt.cxt_zhong_shu_gong_zhen_V221221(self._cat(), freq1="月线", freq2="日线"))
        self.assertTrue(str(next(iter(sig.values()))).startswith("其他"))


class TestSignalsTas(unittest.TestCase):
    """MACD/均线事件型信号（移植自 czsc 0.9.69 signals/tas.py）。"""

    _TAS_SIGNALS = (
        "tas_macd_first_bs_V221216",
        "tas_macd_second_bs_V221201",
        "tas_macd_bs1_V230411",
        "tas_macd_bc_V240307",
        "tas_dma_bs_V240608",
    )

    @classmethod
    def setUpClass(cls):
        from decidra.mcp_server.czsc_lite import Freq, bars_from_df
        cls.c = CZSC(bars_from_df(_synthetic_daily_df(600), Freq.D))

    def test_all_signals_run_and_value_format(self):
        from decidra.mcp_server.czsc_lite import signals_tas
        for name in self._TAS_SIGNALS:
            fn = getattr(signals_tas, name, None)
            self.assertIsNotNone(fn, f"缺少信号函数 {name}")
            sig = dict(fn(self.c))
            self.assertEqual(len(sig), 1, name)
            value = str(next(iter(sig.values())))
            self.assertEqual(len(value.split("_")), 4, f"{name} 值格式非 v1_v2_v3_score: {value}")

    def test_insufficient_bars_return_other(self):
        from decidra.mcp_server.czsc_lite import Freq, bars_from_df, signals_tas
        c_short = CZSC(bars_from_df(_synthetic_daily_df(30), Freq.D))
        for name in self._TAS_SIGNALS:
            sig = dict(getattr(signals_tas, name)(c_short))
            self.assertTrue(
                str(next(iter(sig.values()))).startswith("其他"),
                f"{name} 数据不足时应返回其他",
            )


class TestMultiLevelTool(unittest.TestCase):
    """czsc_multi_level_analysis 工具的联立逻辑（注入合成日线，无网络）。"""

    def setUp(self):
        import decidra.mcp_server.czsc_server as cs
        self.cs = cs
        self._orig = cs._fetch_kline_df
        cs._fetch_kline_df = lambda symbol, period, interval="1d": (_synthetic_daily_df(600), [])

    def tearDown(self):
        self.cs._fetch_kline_df = self._orig

    def _call(self, args: dict) -> dict:
        srv = self.cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(srv.call_tool("czsc_multi_level_analysis", args))
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    def test_default_three_levels(self):
        data = self._call({"symbol": "TEST", "period": "2y"})
        self.assertTrue(data["ok"], f"分析失败: {data}")
        d = data["data"]
        self.assertEqual(set(d["levels"].keys()), {"日线", "周线", "月线"})
        self.assertGreater(d["levels"]["日线"]["bi_count"], 0)
        self.assertGreater(d["levels"]["周线"]["bars"], 50)
        # bars 为 CZSC 按最大笔数裁剪后的 bars_raw，600 个工作日的月线裁剪后约 17 根
        self.assertGreater(d["levels"]["月线"]["bars"], 10)
        self.assertIsInstance(d["cross_level_signals"], dict)
        for level in d["levels"].values():
            for k, v in level["fired_signals"].items():
                self.assertFalse(str(v).startswith("其他"), f"未触发信号 {k}={v} 不应进入")
        self.assertNotIn("data_quality_issues", d, "无质量问题时不应携带该字段")

    def test_freq_subset(self):
        data = self._call({"symbol": "TEST", "freqs": ["日线", "周线"]})
        self.assertTrue(data["ok"])
        self.assertEqual(set(data["data"]["levels"].keys()), {"日线", "周线"})

    def test_unsupported_freq_rejected(self):
        data = self._call({"symbol": "TEST", "freqs": ["日线", "60分钟"]})
        self.assertFalse(data["ok"])
        self.assertIn("仅支持", data["error"])

    def test_quality_issues_surfaced(self):
        self.cs._fetch_kline_df = lambda symbol, period, interval="1d": (
            _synthetic_daily_df(600), ["TEST extreme_values: 存在 1 条记录"])
        data = self._call({"symbol": "TEST"})
        self.assertTrue(data["ok"])
        self.assertIn("data_quality_issues", data["data"])


def _futu_opend_ready() -> bool:
    """FutuOpenD 网关是否在线（决定是否跳过富途真实数据测试）。"""
    import socket
    try:
        socket.create_connection(("127.0.0.1", 11111), timeout=2).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(_futu_opend_ready(), "需 FutuOpenD 网关在线")
class TestCzscFutuHkIntegration(unittest.TestCase):
    """港股真实数据（富途 API）× czsc 精选信号，gated。

    czsc_chan_analysis 工具取数走 yfinance；本用例验证富途数据源的港股 K 线
    同样能构建缠论结构并跑通全部精选信号，补上 HK 市场的真实数据覆盖。
    """

    def test_real_futu_hk_kline_runs_all_curated_signals(self):
        """HK.00700 日线 1y 富途取数：结构应产出，全部精选信号零报错。"""
        import pandas as pd

        from decidra.modules.futu_market import FutuMarket
        from decidra.mcp_server.czsc_server import _CURATED_SIGNALS

        end = datetime.now().date()
        start = end - timedelta(days=365)
        fm = FutuMarket()
        fm.open()
        try:
            df = fm.request_history_kline(
                "HK.00700", start=str(start), end=str(end), ktype="K_DAY"
            )
        finally:
            fm.close()
        self.assertFalse(df is None or df.empty, "富途未返回 K 线数据")
        self.assertGreater(len(df), 100, "日线 1y 应有足够 K 线")

        bars = []
        for i, row in enumerate(df.itertuples(index=False)):
            dt = pd.to_datetime(row.time_key).to_pydatetime()
            bars.append(RawBar(
                symbol="HK.00700", id=i, dt=dt, freq=Freq.D,
                open=float(row.open), close=float(row.close),
                high=float(row.high), low=float(row.low),
                vol=float(row.volume), amount=float(row.turnover),
            ))
        c = CZSC(bars)
        self.assertGreater(len(c.fx_list), 0, "未产生分型")
        self.assertGreater(len(c.bi_list), 0, "未产生笔")

        fired = {}
        errors = {}
        for name in _CURATED_SIGNALS:
            fn = getattr(signals_cxt, name, None)
            self.assertIsNotNone(fn, f"信号函数缺失: {name}")
            try:
                for k, v in dict(fn(c)).items():
                    if not str(v).startswith("其他"):
                        fired[k] = v
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
        self.assertEqual(errors, {}, f"港股数据上信号报错: {errors}")
        for k, v in fired.items():
            self.assertFalse(str(v).startswith("其他"), f"未触发信号 {k}={v} 不应进入")


@unittest.skipUnless(_yfinance_network_ready(), "需联网访问 yfinance")
class TestCzscMultiLevelIntegration(unittest.TestCase):
    """czsc_multi_level_analysis 真实端到端（yfinance 日线 → 重采样 → 三级别联立），gated。"""

    def test_real_yfinance_multi_level(self):
        import decidra.mcp_server.czsc_server as cs

        srv = cs.build_server()
        res = asyncio.new_event_loop().run_until_complete(
            srv.call_tool("czsc_multi_level_analysis", {"symbol": "AAPL", "period": "5y"}))
        content = res[0] if isinstance(res, tuple) else res
        data = json.loads(content[0].text)
        self.assertTrue(data["ok"], f"分析失败: {data}")
        d = data["data"]
        self.assertEqual(set(d["levels"].keys()), {"日线", "周线", "月线"})
        self.assertGreater(d["levels"]["日线"]["bi_count"], 0)
        self.assertGreater(d["levels"]["周线"]["bi_count"], 0)
        self.assertGreater(d["levels"]["月线"]["bars"], 30)
        self.assertIsInstance(d["cross_level_signals"], dict)


if __name__ == "__main__":
    unittest.main()
