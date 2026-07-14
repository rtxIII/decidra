# -*- coding: utf-8 -*-
"""K 线重采样（源自 czsc.utils.bar_generator v0.9.69，仅保留日级以上路径）。

分钟级重采样依赖交易时段日历（feather 数据文件），且当前数据源无分钟级
历史数据，明确不移植；支持 日线 → 周线/月线/季线/年线。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Union

import pandas as pd

from .enum import Freq
from .objects import RawBar

# 可作为重采样目标的日级以上级别
DAY_LEVEL_FREQS = (Freq.D, Freq.W, Freq.M, Freq.S, Freq.Y)


def bars_from_df(df: pd.DataFrame, freq: Freq) -> List[RawBar]:
    """标准化 K 线 DataFrame（symbol/dt/open/close/high/low/vol/amount）转 RawBar。

    czsc_server 与 strategy 包共用的唯一转换入口，id 从 0 起连续编号。
    """
    bars = []
    for i, row in enumerate(df.to_dict("records")):
        bars.append(RawBar(
            symbol=row["symbol"], id=i, dt=row["dt"], freq=freq,
            open=row["open"], close=row["close"], high=row["high"], low=row["low"],
            vol=row["vol"], amount=row["amount"],
        ))
    return bars


def freq_end_date(dt, freq: Union[Freq, str]):
    """返回 dt 所属 freq 周期的结束日期（仅日级以上级别）。

    输入无论是否带时刻（datetime 是 date 的子类）都先归一化到日期，
    保证同一周期内不同时刻的时间戳聚合到同一根 K 线（对齐原版
    freq_end_time 先取 dt.date() 的语义）。

    :param dt: 任意可被 pd.to_datetime 解析的日期
    :param freq: 目标级别（Freq 或其 value 字符串）
    :return: pd.Timestamp 周期结束日期
    """
    if isinstance(dt, datetime) or not isinstance(dt, date):
        dt = pd.to_datetime(dt).date()
    if not isinstance(freq, Freq):
        freq = Freq(freq)
    assert freq in DAY_LEVEL_FREQS, f"仅支持日级以上级别，收到: {freq}"

    dt = pd.to_datetime(dt)
    if freq == Freq.D:
        return dt

    if freq == Freq.W:
        return dt + timedelta(days=5 - dt.isoweekday())

    if freq == Freq.Y:
        return dt.replace(month=12, day=31)

    if freq == Freq.M:
        if dt.month == 12:
            edt = dt.replace(year=dt.year + 1, month=1, day=1)
        else:
            edt = dt.replace(month=dt.month + 1, day=1)
        return edt - timedelta(days=1)

    # Freq.S 季线
    dt_m = dt.month
    if dt_m in (1, 2, 3):
        edt = dt.replace(month=4, day=1)
    elif dt_m in (4, 5, 6):
        edt = dt.replace(month=7, day=1)
    elif dt_m in (7, 8, 9):
        edt = dt.replace(month=10, day=1)
    else:
        edt = dt.replace(year=dt.year + 1, month=1, day=1)
    return edt - timedelta(days=1)


def resample_bars(
    df: pd.DataFrame, target_freq: Union[Freq, str], raw_bars: bool = True, **kwargs
) -> Union[List[RawBar], pd.DataFrame]:
    """将 K 线重采样为日级以上的更大周期（与原版 resample_bars 同语义）。

    :param df: 必须包含列 symbol/dt/open/close/high/low/vol/amount
    :param target_freq: 目标级别（周线/月线/季线/年线；日线原样按日聚合）
    :param raw_bars: True 返回 List[RawBar]，False 返回 DataFrame
    :param kwargs: ``drop_unfinished`` 是否丢弃最后一根未完成 K 线，默认 True
    :return: List[RawBar] 或 DataFrame
    """
    if not isinstance(target_freq, Freq):
        target_freq = Freq(target_freq)
    assert target_freq in DAY_LEVEL_FREQS, f"仅支持日级以上级别，收到: {target_freq}"

    df = df.copy()
    df["freq_edt"] = df["dt"].apply(lambda x: freq_end_date(x, target_freq))
    dfk1 = df.groupby("freq_edt").agg(
        {
            "symbol": "first",
            "dt": "last",
            "open": "first",
            "close": "last",
            "high": "max",
            "low": "min",
            "vol": "sum",
            "amount": "sum",
            "freq_edt": "last",
        }
    )
    dfk1.reset_index(drop=True, inplace=True)
    dfk1["dt"] = dfk1["freq_edt"]
    dfk1 = dfk1[["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]]

    if not raw_bars:
        return dfk1

    _bars = []
    for i, row in enumerate(dfk1.to_dict("records"), 1):
        row.update({"id": i, "freq": target_freq})
        _bars.append(RawBar(**row))

    if kwargs.get("drop_unfinished", True):
        # 清除最后一根未完成的K线
        if pd.to_datetime(df["dt"].iloc[-1]) < _bars[-1].dt:
            _bars.pop()
    return _bars
