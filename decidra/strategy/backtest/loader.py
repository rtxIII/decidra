"""FetcherLoader：把 Decidra 数据源失败切换链适配为回测引擎的 loader 契约。

``BaseEngine.run_backtest`` 期望 ``loader.fetch(codes, start, end, *, fields, interval)``
返回 ``{code: OHLCV DataFrame}``，每个 DataFrame 需满足：
  - DatetimeIndex（升序、去重）；
  - 小写列 open/high/low/close/volume（引擎按**开盘价**成交、**收盘价** mark）；
  - A 股附 pct_chg（``china_a`` 判涨跌停用；百分点，与 Decidra fetcher 口径一致）。

本 loader 按市场路由取数（均免 FutuOpenD 网关）：
  - A 股（``SH./SZ.`` 或 6 位数字码）经 ``decidra.base.data.DataFetcherManager``
    的默认链 [Tdx, Akshare, Baostock, Yfinance]（Tdx 前复权主源）；
  - 港美股（``.HK`` / 其它）经 yfinance 直取（``yf.Ticker.history``）。

港美股不走 A 股链的原因：链中前三家（Tdx/Akshare/Baostock）为 A 股源，Tdx 会把
港股码（如 ``0700.HK``）误解析为 A 股并**静默返回错误数据**（非报错）；yfinance
fetcher 的 ``_convert_stock_code`` 也只认 A 股码。故港美股必须绕开该链、直取 yfinance。

护栏：
  - F1：强校验 open 列存在且全为正值——缺失/非正会让引擎的 ``bar.get("open",
    bar.get("close"))`` 回落到当根 close（信号所见 K 线），构成未来函数。此处
    直接报错而非静默（港美股 yfinance 帧同样经此护栏）。
  - F2：A 股 涨跌停判定走 pct_chg（qfq 连续 pct_chg 无除权日假跳空，优于未复权），
    fetcher 已提供，无需额外处理。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# 目前仅支持日线（Decidra fetcher 为日线数据源）。
_DAILY_INTERVALS = {"1d", "1day", "day", "d", "daily"}

_KEEP_COLUMNS = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
_REQUIRED_COLUMNS = ["open", "high", "low", "close"]


def detect_market(code: str) -> str:
    """按代码判市场：``a``（A股）/``hk``（港股）/``us``（美股/其它）。

    与 backtest CLI 的引擎选择共用同一判定（单一事实来源，CLI 从此处导入）。
    """
    upper = code.upper()
    if upper.endswith(".HK") or upper.startswith("HK."):
        return "hk"
    base = upper.split(".")[0]
    if base.isdigit() and len(base) == 6:
        return "a"
    return "us"


def _to_yfinance_code(code: str) -> str:
    """回测标的码 → yfinance 码。

    ``0700.HK`` 原样；``HK.00700`` → ``0700.HK``（富途式前缀，港股 5 位零填充转
    yfinance 至少 4 位）；``US.AAPL`` → ``AAPL``；``AAPL`` 原样。
    """
    stripped = code.strip()
    upper = stripped.upper()
    if upper.startswith("HK."):
        return f"{int(stripped.split('.', 1)[1]):04d}.HK"
    if upper.startswith("US."):
        return stripped.split(".", 1)[1]
    return stripped


def _default_yfinance_ohlcv(
    yf_code: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """用 yfinance 直取港美股日线 OHLCV（绕开只认 A 股码的 fetcher 链）。

    返回带 ``date`` 列 + 小写 OHLCV 的帧，交由 ``_standardize`` 统一标准化（含
    F1 open 护栏）。yfinance ``end`` 为开区间，+1 日以包含结束当日。延迟导入
    yfinance，保持模块导入期轻量。
    """
    import yfinance as yf

    end_param = None
    if end_date:
        end_param = str(
            pd.Timestamp(end_date).normalize().date() + pd.Timedelta(days=1)
        )
    raw = yf.Ticker(yf_code).history(
        start=start_date or None, end=end_param, interval="1d"
    )
    if raw is None or raw.empty:
        raise ValueError(f"yfinance 未取到 {yf_code} 的 K 线数据")

    index = raw.index
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    close = pd.to_numeric(raw["Close"], errors="coerce")
    volume = pd.to_numeric(raw["Volume"], errors="coerce")
    frame = pd.DataFrame({
        "date": index.normalize(),
        "open": pd.to_numeric(raw["Open"], errors="coerce").values,
        "high": pd.to_numeric(raw["High"], errors="coerce").values,
        "low": pd.to_numeric(raw["Low"], errors="coerce").values,
        "close": close.values,
        "volume": volume.values,
        "amount": (close * volume).values,
    })
    frame["pct_chg"] = frame["close"].pct_change() * 100.0
    return frame


class FetcherLoader:
    """Decidra 数据源链 → 回测引擎 loader 适配器。"""

    name = "decidra_fetcher"

    def __init__(
        self, manager: Optional[object] = None, yfinance_fetch: Optional[object] = None
    ) -> None:
        """
        Args:
            manager: 可选，注入自定义 ``DataFetcherManager``（测试用）。缺省时
                延迟构造默认失败切换链，避免 import 期即拉起数据源依赖。
            yfinance_fetch: 可选，注入港美股取数函数 ``(yf_code, start, end) -> 帧``
                （测试用，无网络）。缺省走 ``_default_yfinance_ohlcv``。
        """
        if manager is None:
            from decidra.base.data import DataFetcherManager

            manager = DataFetcherManager()
        self._manager = manager
        self._yfinance_fetch = yfinance_fetch or _default_yfinance_ohlcv
        # code -> 实际命中的数据源名，供上层记录。
        self.sources: Dict[str, str] = {}

    def fetch(
        self,
        codes: Sequence[str],
        start_date: str = "",
        end_date: str = "",
        *,
        fields: Optional[Sequence[str]] = None,
        interval: str = "1D",
    ) -> Dict[str, pd.DataFrame]:
        """按代码取日线并标准化为引擎期望的 OHLCV 帧。

        Args:
            codes: 标的代码列表（Decidra fetcher 代码风格，如 600000 / 000001）。
            start_date / end_date: 日期区间（``YYYY-MM-DD``），空串表示由 fetcher 默认。
            fields: 额外基本面字段——P1 忽略（富集为 P3 范围）。
            interval: K 线级别，目前仅支持日线。

        Returns:
            ``{code: DataFrame}``，DataFrame 为 DatetimeIndex + 小写 OHLCV(+pct_chg)。
        """
        del fields  # extra_fields 富集为 P3 范围，P1 不消费。
        if interval and interval.lower() not in _DAILY_INTERVALS:
            raise ValueError(f"FetcherLoader 目前仅支持日线（interval=1D），收到: {interval!r}")

        data_map: Dict[str, pd.DataFrame] = {}
        for code in codes:
            if detect_market(code) in ("hk", "us"):
                # 港美股绕开 A 股 fetcher 链（Tdx 会静默误取错数据），直取 yfinance
                df = self._yfinance_fetch(_to_yfinance_code(code), start_date, end_date)
                self.sources[code] = "yfinance"
            else:
                df, source = self._manager.get_daily_data(
                    stock_code=code,
                    start_date=start_date or None,
                    end_date=end_date or None,
                )
                self.sources[code] = source
            data_map[code] = self._standardize(code, df)
        return data_map

    @staticmethod
    def _standardize(code: str, df: pd.DataFrame) -> pd.DataFrame:
        """标准化单标的帧：DatetimeIndex + 小写 OHLCV，并施加 F1 open 护栏。"""
        out = df.copy()

        # Decidra fetcher 以 date 列 + RangeIndex 返回，转为 DatetimeIndex。
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        else:
            out.index = pd.to_datetime(out.index)
        out = out[~out.index.duplicated(keep="last")].sort_index()

        missing = [c for c in _REQUIRED_COLUMNS if c not in out.columns]
        if missing:
            raise ValueError(f"{code}: 缺少必需列 {missing}")

        # F1：成交价取当根 open；缺失/非正会触发引擎回落到当根 close（未来函数）。
        open_col = pd.to_numeric(out["open"], errors="coerce")
        bad = int(open_col.isna().sum() + (open_col <= 0).sum())
        if bad:
            raise ValueError(
                f"F1 {code}: open 列含 {bad} 个缺失/非正值，无法保证按开盘价成交（防未来函数）"
            )

        keep = [c for c in _KEEP_COLUMNS if c in out.columns]
        return out[keep]
