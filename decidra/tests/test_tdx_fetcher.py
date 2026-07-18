"""TdxFetcher（通达信行情数据源）单元测试。

确定性用例（无网络、不 mock）：代码→市场推断、原始数据标准化、失败切换链注册。
集成用例（需 TDX 服务器 7709 可达）：真实取沪深日线，gated。
"""
import socket
import unittest
from pathlib import Path
import sys

import pandas as pd

src_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(src_path))

from decidra.base.data import STANDARD_COLUMNS, DataFetcherManager
from decidra.modules.fetcher import TdxFetcher
from decidra.modules.fetcher.tdx import TDX_HQ_SERVERS, code_to_market


def _tdx_server_ready() -> bool:
    """任一候选 TDX 服务器 7709 端口可达则视为可跑集成用例。"""
    for ip, port in TDX_HQ_SERVERS:
        try:
            socket.create_connection((ip, port), timeout=3).close()
            return True
        except OSError:
            continue
    return False


class TestCodeToMarket(unittest.TestCase):
    """代码→市场推断（1=上海，0=深圳）。"""

    def test_bare_shanghai_codes(self):
        for code in ("600000", "601398", "688981", "510300", "900901"):
            self.assertEqual(code_to_market(code)[0], 1, code)

    def test_bare_shenzhen_codes(self):
        for code in ("000001", "002415", "300750", "159915", "200011"):
            self.assertEqual(code_to_market(code)[0], 0, code)

    def test_suffixed_codes(self):
        self.assertEqual(code_to_market("600000.SH"), (1, "600000"))
        self.assertEqual(code_to_market("000001.SZ"), (0, "000001"))

    def test_strips_and_uppercases(self):
        self.assertEqual(code_to_market(" 600000.sh "), (1, "600000"))


class TestNormalizeData(unittest.TestCase):
    """原始通达信数据 → 标准列名（无网络，构造 tdxpy 形状的原始 df）。"""

    def _raw_df(self):
        # tdxpy to_df 形状：open/close/high/low/vol/amount/datetime
        return pd.DataFrame({
            "open": [9.08, 8.92, 8.85],
            "close": [9.31, 8.85, 8.87],
            "high": [9.32, 8.94, 8.97],
            "low": [9.06, 8.80, 8.82],
            "vol": [1047581.0, 755826.0, 796240.0],
            "amount": [9.667e8, 6.704e8, 7.078e8],
            "datetime": ["2026-07-15 15:00", "2026-07-16 15:00", "2026-07-17 15:00"],
        })

    def test_standard_columns_present(self):
        out = TdxFetcher()._normalize_data(self._raw_df(), "600000")
        for col in STANDARD_COLUMNS:
            self.assertIn(col, out.columns, col)
        self.assertIn("code", out.columns)

    def test_no_duplicate_volume_column(self):
        # 参考实现的 bug：vol→volume 与自带 volume 撞名产生重复列；本源应只有一列
        out = TdxFetcher()._normalize_data(self._raw_df(), "600000")
        self.assertEqual(list(out.columns).count("volume"), 1)

    def test_date_parsed_and_code_set(self):
        out = TdxFetcher()._normalize_data(self._raw_df(), "600000")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(out["date"]))
        self.assertTrue((out["code"] == "600000").all())

    def test_pct_chg_computed_from_close(self):
        out = TdxFetcher()._normalize_data(self._raw_df(), "600000")
        # 第二根：(8.85-9.31)/9.31*100 ≈ -4.94
        self.assertAlmostEqual(out["pct_chg"].iloc[1], round((8.85 - 9.31) / 9.31 * 100, 2), places=2)
        self.assertTrue(pd.isna(out["pct_chg"].iloc[0]))


class TestQfqAdjustment(unittest.TestCase):
    """前复权(qfq)——合成除权除息事件，无网络。"""

    def _bars(self):
        # tdxpy 形状：4 个交易日
        return pd.DataFrame({
            "datetime": ["2026-01-05 15:00", "2026-01-06 15:00",
                         "2026-01-07 15:00", "2026-01-08 15:00"],
            "open": [10.0, 10.0, 9.8, 9.9],
            "high": [10.0, 10.0, 9.8, 9.9],
            "low": [10.0, 10.0, 9.8, 9.9],
            "close": [10.0, 10.0, 9.8, 9.9],
            "vol": [100.0, 100.0, 100.0, 100.0],
            "amount": [1000.0, 1000.0, 1000.0, 1000.0],
        })

    def _xdxr_cash_div(self):
        # 2026-01-07 每10股派 2.0 元（除息日）；含一条非 category==1 行验证过滤
        return pd.DataFrame({
            "category": [1, 5],
            "year": [2026, 2025],
            "month": [1, 12],
            "day": [7, 1],
            "fenhong": [2.0, 0.0],
            "peigu": [0.0, 0.0],
            "peigujia": [0.0, 0.0],
            "songzhuangu": [0.0, 0.0],
        })

    def test_anchor_latest_unchanged(self):
        # 末次事件后（含除息当日及之后）adj=1，价格不变
        out = TdxFetcher._apply_qfq(self._bars(), self._xdxr_cash_div())
        self.assertAlmostEqual(out["close"].iloc[3], 9.9, places=3)
        self.assertAlmostEqual(out["close"].iloc[2], 9.8, places=3)

    def test_pre_event_scaled_by_dividend_factor(self):
        # 除息前(01-05/01-06)按因子 r=(10-0.2)/10=0.98 缩放
        out = TdxFetcher._apply_qfq(self._bars(), self._xdxr_cash_div())
        self.assertAlmostEqual(out["close"].iloc[0], round(10.0 * 0.98, 3), places=3)
        self.assertAlmostEqual(out["close"].iloc[1], round(10.0 * 0.98, 3), places=3)

    def test_ex_dividend_gap_removed(self):
        # 原始 01-06→01-07：10.0→9.8（含 0.2 除息）；qfq 后应连续（9.8→9.8）
        out = TdxFetcher._apply_qfq(self._bars(), self._xdxr_cash_div())
        self.assertAlmostEqual(out["close"].iloc[1], out["close"].iloc[2], places=3)

    def test_no_events_returns_unchanged(self):
        empty = pd.DataFrame(columns=["category", "year", "month", "day",
                                      "fenhong", "peigu", "peigujia", "songzhuangu"])
        out = TdxFetcher._apply_qfq(self._bars(), empty)
        self.assertTrue((out["close"] == self._bars()["close"]).all())

    def test_columns_preserved(self):
        out = TdxFetcher._apply_qfq(self._bars(), self._xdxr_cash_div())
        self.assertEqual(list(out.columns), list(self._bars().columns))

    def test_invalid_adjust_rejected(self):
        with self.assertRaises(ValueError):
            TdxFetcher(adjust="hfq")


class TestManagerRegistration(unittest.TestCase):
    """TdxFetcher 已接入默认失败切换链且为 A 股主源。"""

    def test_priority_is_one(self):
        self.assertEqual(TdxFetcher().priority, 1)

    def test_registered_in_default_manager(self):
        manager = DataFetcherManager()
        self.assertIn("TdxFetcher", manager.available_fetchers)

    def test_tdx_is_primary_source(self):
        manager = DataFetcherManager()
        names = manager.available_fetchers
        # tdx 为链首（A 股主源），akshare 紧随其后
        self.assertEqual(names[0], "TdxFetcher")
        self.assertLess(names.index("TdxFetcher"), names.index("AkshareFetcher"))
        self.assertLess(names.index("AkshareFetcher"), names.index("BaostockFetcher"))


@unittest.skipUnless(_tdx_server_ready(), "需 TDX 行情服务器 7709 端口可达")
class TestTdxFetcherIntegration(unittest.TestCase):
    """真实通达信服务器取数（沪深两市）。"""

    def test_fetch_shanghai_daily(self):
        df = TdxFetcher().get_daily_data("600000", days=30)
        self.assertFalse(df.empty)
        for col in STANDARD_COLUMNS:
            self.assertIn(col, df.columns, col)
        self.assertTrue((df["close"] > 0).all())
        self.assertTrue((df["date"].diff().dropna() > pd.Timedelta(0)).all())

    def test_fetch_shenzhen_daily(self):
        df = TdxFetcher().get_daily_data("000001", days=30)
        self.assertFalse(df.empty)
        self.assertTrue((df["close"] > 0).all())

    def test_date_range_respected(self):
        df = TdxFetcher().get_daily_data("600000", days=120)
        span = (df["date"].max() - df["date"].min()).days
        # 120 日历日区间内应有数据，且不越界到未来
        self.assertGreater(len(df), 0)
        self.assertLessEqual(df["date"].max(), pd.Timestamp.now().normalize())
        self.assertGreaterEqual(span, 0)

    def test_qfq_anchors_latest_and_adjusts_history(self):
        # 600000 为长期现金分红股：qfq 最新价与不复权一致（锚点），历史价被下调
        qfq = TdxFetcher(adjust="qfq").get_daily_data("600000", days=400).set_index("date")["close"]
        raw = TdxFetcher(adjust="none").get_daily_data("600000", days=400).set_index("date")["close"]
        common = qfq.index.intersection(raw.index)
        self.assertGreater(len(common), 0)
        # 锚点：最新一根复权价 == 原始价
        self.assertAlmostEqual(qfq.loc[common.max()], raw.loc[common.max()], places=2)
        # 历史确有下调（存在除息），且 qfq 不高于原始价
        self.assertTrue((qfq.loc[common] <= raw.loc[common] + 1e-6).all())
        self.assertLess(qfq.loc[common.min()], raw.loc[common.min()])


if __name__ == "__main__":
    unittest.main()
