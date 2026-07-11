"""czsc_lite 的轻量兼容层。

替代 vendored czsc 代码原本依赖的 loguru / deprecated / czsc.utils.corr，使
czsc_lite 仅依赖 numpy/pandas/sklearn（均已随 Decidra 安装），零新增第三方依赖。
"""

from __future__ import annotations

import logging
from typing import Union

import numpy as np


class _LoguruShim(logging.Logger):
    """stdlib logging.Logger + loguru 专有方法的 no-op（disable/enable/add/remove）。

    vendored czsc 代码调用了 loguru 的 ``logger.disable(...)``，stdlib 无此方法，
    故补 no-op，避免引入 loguru 依赖。
    """

    def disable(self, *args, **kwargs) -> None:  # noqa: D401
        """no-op（兼容 loguru.disable）。"""

    def enable(self, *args, **kwargs) -> None:
        """no-op（兼容 loguru.enable）。"""

    def add(self, *args, **kwargs) -> int:
        """no-op（兼容 loguru.add）。"""
        return 0

    def remove(self, *args, **kwargs) -> None:
        """no-op（兼容 loguru.remove）。"""


logger = _LoguruShim("czsc_lite")
logger.addHandler(logging.NullHandler())


def deprecated(*args, **kwargs):
    """no-op 版 ``deprecated`` 装饰器（替代 Deprecated 包）。"""
    def _decorator(func):
        return func
    if args and callable(args[0]):
        return args[0]
    return _decorator


def single_linear(y: Union[np.ndarray, list], x: Union[np.ndarray, list] = None) -> dict:
    """单变量线性拟合（源自 czsc.utils.corr.single_linear，纯数学，无绘图依赖）。

    Args:
        y: 目标序列。
        x: 单变量值；缺省为 ``range(len(y))``。

    Returns:
        ``{"slope": .., "intercept": .., "r2": ..}``。
    """
    if not x:
        x = list(range(len(y)))

    x_squred_sum = sum([x1 * x1 for x1 in x])
    xy_product_sum = sum([x[i] * y[i] for i in range(len(x))])
    num = len(x)
    x_sum = sum(x)
    y_sum = sum(y)
    delta = float(num * x_squred_sum - x_sum * x_sum)
    if delta == 0:
        return {"slope": 0, "intercept": 0, "r2": 0}

    y_intercept = (1 / delta) * (x_squred_sum * y_sum - x_sum * xy_product_sum)
    slope = (1 / delta) * (num * xy_product_sum - x_sum * y_sum)

    y_mean = np.mean(y)
    ss_tot = sum([(y1 - y_mean) * (y1 - y_mean) for y1 in y]) + 0.00001
    ss_err = sum(
        [(y[i] - slope * x[i] - y_intercept) * (y[i] - slope * x[i] - y_intercept) for i in range(len(x))]
    )
    rsq = 1 - ss_err / ss_tot

    return {"slope": round(slope, 4), "intercept": round(y_intercept, 4), "r2": round(rsq, 4)}
