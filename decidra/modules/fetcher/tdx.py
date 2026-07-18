# -*- coding: utf-8 -*-
"""
===================================
TdxFetcher - 通达信行情数据源 (Priority 1, A 股主源)
===================================

数据来源：通达信（TDX）行情服务器，经 tdxpy 直连（TDX 私有二进制协议 TCP 长连接）。
特点：免费、无需 Token、无 IP 限频；相比爬虫类数据源更稳定。

依赖：仅 tdxpy（其自身只依赖 pandas，不引入 httpx/py-mini-racer 等重依赖）。

复权：
- 默认**前复权(qfq)**，与 akshare/baostock 一致（可作为失败切换链中的等价回退）。TDX 协议本身
  返回不复权原始价，本源用除权除息信息（get_xdxr_info）按 QUANTAXIS/pytdx 标准公式重构复权价，
  以最新一根为基准(adj=1)、历史价回溯缩放，消除除息除权造成的价格跳空。
- 仅调整 OHLC；vol/amount 保持原值。
- 复权方法学差异：本源走 xdxr「因子复权」，东财(akshare)走「涨跌幅复权」，二者在近段一致、
  远端历史绝对价位有小幅（约 1%）差异，均为合法实现，不影响缠论关心的局部结构与跳空。
- ``adjust="none"`` 可关闭复权取原始价。

其它约束：
- **pct_chg 本地计算**：TDX 不返回涨跌幅，本源由相邻收盘价计算。
- **单次 800 根上限**：TDX 协议单包最多 800 根 K 线，跨区间取数由本源分页翻页拼接。
"""

import logging
from typing import List, Optional, Tuple

import pandas as pd

from decidra.base.data import (
    BaseFetcher,
    DataFetchError,
    DataSourceUnavailableError,
    STANDARD_COLUMNS,
)

logger = logging.getLogger(__name__)


# 通达信行情服务器候选表（源自 mootdx 维护的服务器清单，取地理分布多样的稳定子集）。
# 逐台尝试连接，任一台成功即用；公共服务器可能随时间失效，多台冗余以保证可用性。
TDX_HQ_SERVERS: Tuple[Tuple[str, int], ...] = (
    ("180.153.18.170", 7709),   # 上海电信
    ("124.70.176.52", 7709),    # 上海双线
    ("124.71.187.72", 7709),    # 上海双线
    ("110.41.147.114", 7709),   # 深圳双线
    ("47.113.94.204", 7709),    # 深圳双线
    ("121.36.54.217", 7709),    # 北京双线
    ("124.71.85.110", 7709),    # 广州双线
    ("119.97.185.59", 7709),    # 武汉电信
)

# TDX K 线频次：9 = 日线
_FREQ_DAILY = 9

# 单次请求 K 线上限（TDX 协议约束）
_MAX_BARS_PER_REQUEST = 800

# 分页翻页硬上限（防御性：8 页约 6400 根日线 ≈ 25 年，远超实际需求）
_MAX_PAGES = 8


def code_to_market(stock_code: str) -> Tuple[int, str]:
    """将股票代码归一化为 (市场, 纯代码)。

    市场：1 = 上海，0 = 深圳。支持 ``600000.SH`` 与裸 ``600000`` 两种写法；
    裸代码按首位字符推断（6/5/9 → 上海，其余 → 深圳）。

    Args:
        stock_code: 股票代码。

    Returns:
        (market, pure_code) 元组。
    """
    code = stock_code.strip().upper()
    if "." in code:
        pure, suffix = code.split(".", 1)
        market = 1 if suffix in ("SH", "1") else 0
    else:
        pure = code
        market = 1 if pure[:1] in ("5", "6", "9") else 0
    return market, pure


class TdxFetcher(BaseFetcher):
    """
    通达信行情数据源实现

    优先级：1（A 股主源——已前复权且免费/无 key/无限频，最可靠）
    数据来源：通达信行情服务器（tdxpy 直连）

    关键策略：
    - 多服务器候选，逐台连接直至成功（失败切换）
    - 跨日期区间取数自动分页翻 800 根上限
    - 每次取数独立建连并释放，无长驻连接
    """

    name = "TdxFetcher"
    priority = 1

    def __init__(
        self,
        servers: Optional[Tuple[Tuple[str, int], ...]] = None,
        timeout: int = 6,
        adjust: str = "qfq",
    ):
        """
        初始化 TdxFetcher

        Args:
            servers: 服务器候选表 (ip, port)，缺省用内置 TDX_HQ_SERVERS。
            timeout: 单台服务器连接超时（秒）。
            adjust: 复权方式，``"qfq"`` 前复权（默认）或 ``"none"`` 不复权。
        """
        if adjust not in ("qfq", "none"):
            raise ValueError(f"不支持的复权方式: {adjust}（仅 'qfq' 或 'none'）")
        self.servers = servers or TDX_HQ_SERVERS
        self.timeout = timeout
        self.adjust = adjust

    def _connect(self):
        """逐台尝试连接候选服务器，返回已连接的 TdxHq_API。

        Raises:
            DataSourceUnavailableError: 所有候选服务器均连接失败。
        """
        from tdxpy.hq import TdxHq_API

        errors = []
        for ip, port in self.servers:
            api = TdxHq_API(heartbeat=False, auto_retry=True, raise_exception=False)
            try:
                if api.connect(ip, int(port), time_out=self.timeout):
                    logger.debug(f"[{self.name}] 已连接 {ip}:{port}")
                    return api
                errors.append(f"{ip}:{port} 连接返回空")
            except Exception as e:
                errors.append(f"{ip}:{port} {e}")
                logger.debug(f"[{self.name}] 连接 {ip}:{port} 失败: {e}")
        raise DataSourceUnavailableError(
            f"[{self.name}] 所有通达信服务器连接失败: " + "; ".join(errors)
        )

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从通达信取日线原始数据（分页翻页 + 按区间过滤）。

        Args:
            stock_code: 股票代码，如 '600000'、'000001'、'600000.SH'。
            start_date: 开始日期 'YYYY-MM-DD'。
            end_date: 结束日期 'YYYY-MM-DD'。

        Returns:
            原始 K 线 DataFrame（tdxpy 列名：open/close/high/low/vol/amount/datetime 等）。
        """
        market, pure = code_to_market(stock_code)

        api = self._connect()
        try:
            frames: List[pd.DataFrame] = []
            offset = 0
            for _ in range(_MAX_PAGES):
                data = api.get_security_bars(
                    _FREQ_DAILY, market, pure, offset, _MAX_BARS_PER_REQUEST
                )
                if not data:
                    break
                page = api.to_df(data)
                # 每页内按时间升序，start=0 为最新一批，offset 增大取更早批次
                frames.insert(0, page)
                oldest = str(page["datetime"].iloc[0])[:10]
                if len(data) < _MAX_BARS_PER_REQUEST or oldest < start_date:
                    break
                offset += _MAX_BARS_PER_REQUEST

            if not frames:
                raise DataFetchError(f"[{self.name}] 未取到 {stock_code} 的 K 线数据")

            df = pd.concat(frames, ignore_index=True)
            df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

            # 复权在按区间过滤之前施加：以完整历史锚定，避免窗口首根 preclose 缺失导致的边界误差
            if self.adjust == "qfq":
                xdxr_raw = api.get_xdxr_info(market, pure)
                xdxr = api.to_df(xdxr_raw) if xdxr_raw else pd.DataFrame()
                df = self._apply_qfq(df, xdxr)
        finally:
            api.disconnect()

        df["_date"] = df["datetime"].astype(str).str[:10]
        df = df[(df["_date"] >= start_date) & (df["_date"] <= end_date)].reset_index(drop=True)
        logger.info(f"[{self.name}] {stock_code} 取到 {len(df)} 条日线 ({start_date}~{end_date}, adjust={self.adjust})")
        return df

    @staticmethod
    def _apply_qfq(df: pd.DataFrame, xdxr: pd.DataFrame) -> pd.DataFrame:
        """对 OHLC 施加前复权(qfq)，采用 QUANTAXIS/pytdx 的除权除息重构公式。

        以最新一根为基准(adj=1)，历史价按除权除息因子回溯缩放，消除除息除权跳空；
        仅调整 open/high/low/close，vol/amount 保持原值。无除权除息事件时原样返回。

        Args:
            df: 原始 K 线（tdxpy 形状，含 datetime/open/high/low/close，按时间升序）。
            xdxr: get_xdxr_info 返回的除权除息表（含 category/year/month/day/fenhong/peigu/...）。

        Returns:
            复权后的 K 线 DataFrame（列结构与 df 一致）。
        """
        events = xdxr[xdxr["category"] == 1] if ("category" in xdxr.columns and not xdxr.empty) else None
        if events is None or events.empty:
            return df

        info = events.copy()
        info["_dt"] = pd.to_datetime(dict(year=info["year"], month=info["month"], day=info["day"]))
        info = info.set_index("_dt").sort_index()[["fenhong", "peigu", "peigujia", "songzhuangu"]]

        work = df.copy()
        work.index = pd.to_datetime(work["datetime"].astype(str).str[:10])
        work["_if_trade"] = True

        # 仅并入落在数据区间内的除权除息事件（事件日通常即交易日，对齐到已有行）
        merged = pd.concat([work, info[work.index[0]:]], axis=1)
        merged["_if_trade"] = merged["_if_trade"].fillna(False)
        carry = ["datetime", "open", "high", "low", "close", "vol", "amount"]
        merged[carry] = merged[carry].ffill()
        merged[["fenhong", "peigu", "peigujia", "songzhuangu"]] = \
            merged[["fenhong", "peigu", "peigujia", "songzhuangu"]].fillna(0)

        merged["_preclose"] = (
            merged["close"].shift(1) * 10 - merged["fenhong"] + merged["peigu"] * merged["peigujia"]
        ) / (10 + merged["peigu"] + merged["songzhuangu"])
        merged["_adj"] = (merged["_preclose"].shift(-1) / merged["close"]).fillna(1)[::-1].cumprod()[::-1]

        for col in ("open", "high", "low", "close"):
            merged[col] = (merged[col] * merged["_adj"]).round(3)

        result = merged[merged["_if_trade"]][df.columns].reset_index(drop=True)
        return result

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """标准化通达信数据列名。

        tdxpy 列名：open/close/high/low/vol/amount/datetime；映射到标准列名
        date/open/high/low/close/volume/amount/pct_chg（pct_chg 由收盘价计算）。
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["datetime"].astype(str).str[:10])
        df = df.rename(columns={"vol": "volume"})
        df["code"] = stock_code
        df["pct_chg"] = (df["close"].pct_change() * 100).round(2)

        keep_cols = ["code"] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        return df[existing_cols]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = TdxFetcher()

    print("=" * 50)
    print("测试沪市股票 600000 浦发银行")
    print("=" * 50)
    try:
        result = fetcher.get_daily_data("600000", days=30)
        print(f"获取成功，共 {len(result)} 条数据")
        print(result.tail())
    except Exception as exc:
        print(f"获取失败: {exc}")

    print("\n" + "=" * 50)
    print("测试深市股票 000001 平安银行")
    print("=" * 50)
    try:
        result = fetcher.get_daily_data("000001", days=30)
        print(f"获取成功，共 {len(result)} 条数据")
        print(result.tail())
    except Exception as exc:
        print(f"获取失败: {exc}")
