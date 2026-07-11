"""均线 / MACD 缓存更新（talib-free）。

源自 czsc.signals.tas 的 update_ma_cache / update_macd_cache，将 talib 的 ta.MA
替换为本地纯 numpy 实现（.ta 的 SMA/EMA/WMA），使缠论信号计算无需 TA-Lib。
"""

from __future__ import annotations

import numpy as np

from .ta import SMA, EMA, WMA, MACD

# 纯 numpy 支持的均线类型（cxt 缠论信号常用 SMA/EMA）。
_MA_FUNCS = {"SMA": SMA, "EMA": EMA, "WMA": WMA}


def _ma(close: np.ndarray, timeperiod: int, ma_type: str) -> np.ndarray:
    """按类型计算均线（纯 numpy）。"""
    func = _MA_FUNCS.get(ma_type.upper())
    if func is None:
        raise ValueError(f"czsc_lite 仅支持 SMA/EMA/WMA 均线，收到: {ma_type}")
    return func(close, timeperiod=timeperiod)


def update_ma_cache(c, **kwargs) -> str:
    """更新均线缓存（talib-free）。

    Args:
        c: CZSC 对象。
        kwargs: ``ma_type``（SMA/EMA/WMA）、``timeperiod``。

    Returns:
        cache_key，如 ``"SMA#5"``。
    """
    timeperiod = int(kwargs["timeperiod"])
    ma_type = kwargs.get("ma_type", "SMA").upper()

    cache_key = f"{ma_type}#{timeperiod}"
    if c.bars_raw[-1].cache and c.bars_raw[-1].cache.get(cache_key, None):
        return cache_key

    last_cache = dict(c.bars_raw[-2].cache) if c.bars_raw[-2].cache else dict()
    if cache_key not in last_cache.keys() or len(c.bars_raw) < timeperiod + 15:
        close = np.array([x.close for x in c.bars_raw])
        ma = _ma(close, timeperiod, ma_type)
        assert len(ma) == len(close)
        for i in range(len(close)):
            _c = dict(c.bars_raw[i].cache) if c.bars_raw[i].cache else dict()
            _c.update({cache_key: ma[i] if ma[i] else close[i]})
            c.bars_raw[i].cache = _c
    else:
        close = np.array([x.close for x in c.bars_raw[-timeperiod - 10:]])
        ma = _ma(close, timeperiod, ma_type)
        for i in range(1, 6):
            _c = dict(c.bars_raw[-i].cache) if c.bars_raw[-i].cache else dict()
            _c.update({cache_key: ma[-i]})
            c.bars_raw[-i].cache = _c
    return cache_key


def update_macd_cache(c, **kwargs) -> str:
    """更新 MACD 缓存（纯 numpy）。

    Args:
        c: CZSC 对象。
        kwargs: ``fastperiod`` / ``slowperiod`` / ``signalperiod``。

    Returns:
        cache_key，如 ``"MACD12#26#9"``。
    """
    fastperiod = int(kwargs.get("fastperiod", 12))
    slowperiod = int(kwargs.get("slowperiod", 26))
    signalperiod = int(kwargs.get("signalperiod", 9))

    cache_key = f"MACD{fastperiod}#{slowperiod}#{signalperiod}"
    if c.bars_raw[-1].cache and c.bars_raw[-1].cache.get(cache_key, None):
        return cache_key

    min_count = signalperiod + slowperiod + 168
    last_cache = dict(c.bars_raw[-2].cache) if c.bars_raw[-2].cache else dict()
    if cache_key not in last_cache.keys() or len(c.bars_raw) < min_count + 15:
        close = np.array([x.close for x in c.bars_raw])
        dif, dea, macd = MACD(close, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod)
        for i in range(len(close)):
            _c = dict(c.bars_raw[i].cache) if c.bars_raw[i].cache else dict()
            dif_i = dif[i] if dif[i] else 0
            dea_i = dea[i] if dea[i] else 0
            macd_i = macd[i] if macd[i] else 0
            _c.update({cache_key: {"dif": dif_i, "dea": dea_i, "macd": macd_i}})
            c.bars_raw[i].cache = _c
    else:
        close = np.array([x.close for x in c.bars_raw[-min_count - 10:]])
        dif, dea, macd = MACD(close, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod)
        for i in range(1, 6):
            _c = dict(c.bars_raw[-i].cache) if c.bars_raw[-i].cache else dict()
            _c.update({cache_key: {"dif": dif[-i], "dea": dea[-i], "macd": macd[-i]}})
            c.bars_raw[-i].cache = _c
    return cache_key
