"""MACD/均线 事件型信号（移植自 czsc 0.9.69 signals/tas.py，逐字提取）。

入选原则与 czsc_resonance 信号集一致：只收事件型（背驰/买卖点/顺势回调），
排除状态型（多头/空头等每根 K 线都有值的信号，接入告警会造成每日轰炸）。
指标缓存走本包 tas_cache（update_macd_cache / update_ma_cache）。
"""

from collections import OrderedDict

import numpy as np

from .analyze import CZSC
from .objects import Direction
from .sig import create_single_signal, fast_slow_cross, get_sub_elements
from .tas_cache import update_ma_cache, update_macd_cache

def tas_macd_first_bs_V221216(c: CZSC, **kwargs):
    """MACD金叉死叉判断第一买卖点

    参数模板："{freq}_D{di}MACD{fastperiod}#{slowperiod}#{signalperiod}_BS1辅助V221216"

    **信号逻辑：**

    1. 最近一次交叉为死叉，且前面两次死叉都在零轴下方，价格创新低，那么一买即将出现；一卖反之。
    2. 或 最近一次交叉为金叉，且前面三次死叉都在零轴下方，价格创新低，那么一买即将出现；一卖反之。

    **信号列表：**

    - Signal('15分钟_D1MACD12#26#9_BS1辅助V221216_一买_死叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS1辅助V221216_一买_金叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS1辅助V221216_一卖_金叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS1辅助V221216_一卖_死叉_任意_0')

    :param c: CZSC对象
    :param di: 倒数第i根K线
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    fastperiod = int(kwargs.get("fastperiod", 12))
    slowperiod = int(kwargs.get("slowperiod", 26))
    signalperiod = int(kwargs.get("signalperiod", 9))

    # cache_key = f"MACD"
    cache_key = update_macd_cache(c, **kwargs)
    k1, k2, k3 = f"{c.freq.value}_D{di}MACD{fastperiod}#{slowperiod}#{signalperiod}_BS1辅助V221216".split("_")
    bars = get_sub_elements(c.bars_raw, di=di, n=300)

    v1 = "其他"
    v2 = "任意"
    if len(bars) >= 100:
        dif = [x.cache[cache_key]["dif"] for x in bars]
        dea = [x.cache[cache_key]["dea"] for x in bars]
        macd = [x.cache[cache_key]["macd"] for x in bars]
        n_bars = bars[-10:]
        m_bars = bars[-100:-10]
        high_n = max([x.high for x in n_bars])
        low_n = min([x.low for x in n_bars])
        high_m = max([x.high for x in m_bars])
        low_m = min([x.low for x in m_bars])

        cross = fast_slow_cross(dif, dea)
        up = [x for x in cross if x["类型"] == "金叉" and x["距离"] > 5]
        dn = [x for x in cross if x["类型"] == "死叉" and x["距离"] > 5]

        b1_con1a = len(cross) > 3 and cross[-1]["类型"] == "死叉" and cross[-1]["慢线"] < 0
        b1_con1b = len(cross) > 3 and cross[-1]["类型"] == "金叉" and dn[-1]["慢线"] < 0
        b1_con2 = len(dn) > 3 and dn[-2]["慢线"] < 0 and dn[-3]["慢线"] < 0
        b1_con3 = len(macd) > 10 and macd[-1] > macd[-2]
        if low_n < low_m and (b1_con1a or b1_con1b) and b1_con2 and b1_con3:
            v1 = "一买"

        s1_con1a = len(cross) > 3 and cross[-1]["类型"] == "金叉" and cross[-1]["慢线"] > 0
        s1_con1b = len(cross) > 3 and cross[-1]["类型"] == "死叉" and up[-1]["慢线"] > 0
        s1_con2 = len(up) > 3 and up[-2]["慢线"] > 0 and up[-3]["慢线"] > 0
        s1_con3 = len(macd) > 10 and macd[-1] < macd[-2]
        if high_n > high_m and (s1_con1a or s1_con1b) and s1_con2 and s1_con3:
            v1 = "一卖"

        v2 = cross[-1]["类型"]

    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1, v2=v2)


def tas_macd_second_bs_V221201(c: CZSC, **kwargs):
    """MACD金叉死叉判断第二买卖点

    参数模板："{freq}_D{di}MACD{fastperiod}#{slowperiod}#{signalperiod}_BS2辅助V221201"

    **信号逻辑：**

    1. 最近一次交叉为死叉，DEA大于0，且前面两次死叉都在零轴下方，那么二买即将出现；二卖反之。
    2. 或 最近一次交叉为金叉，且前面三次死叉中前两次都在零轴下方，后一次在零轴上方，那么二买即将出现；二卖反之。

    **信号列表：**

    - Signal('15分钟_D1MACD12#26#9_BS2辅助V221201_二买_死叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS2辅助V221201_二买_金叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS2辅助V221201_二卖_死叉_任意_0')
    - Signal('15分钟_D1MACD12#26#9_BS2辅助V221201_二卖_金叉_任意_0')

    :param c: CZSC对象
    :param di: 倒数第i根K线
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    fastperiod = int(kwargs.get("fastperiod", 12))
    slowperiod = int(kwargs.get("slowperiod", 26))
    signalperiod = int(kwargs.get("signalperiod", 9))

    cache_key = update_macd_cache(c, **kwargs)
    k1, k2, k3 = f"{c.freq.value}_D{di}MACD{fastperiod}#{slowperiod}#{signalperiod}_BS2辅助V221201".split("_")
    bars = get_sub_elements(c.bars_raw, di=di, n=350)[50:]

    v1 = "其他"
    v2 = "任意"
    if len(bars) >= 100:
        dif = [x.cache[cache_key]["dif"] for x in bars]
        dea = [x.cache[cache_key]["dea"] for x in bars]
        macd = [x.cache[cache_key]["macd"] for x in bars]

        cross = fast_slow_cross(dif, dea)
        up = [x for x in cross if x["类型"] == "金叉" and x["距离"] > 5]
        dn = [x for x in cross if x["类型"] == "死叉" and x["距离"] > 5]

        b2_con1a = len(cross) > 3 and cross[-1]["类型"] == "死叉" and cross[-1]["慢线"] > 0 and cross[-1]["距今"] > 5
        b2_con1b = len(cross) > 3 and cross[-1]["类型"] == "金叉" and dn[-1]["慢线"] > 0 and cross[-1]["距今"] < 5
        b2_con2 = len(dn) > 4 and dn[-3]["慢线"] < 0 and dn[-2]["慢线"] < 0
        b2_con3 = len(macd) > 10 and macd[-1] > macd[-2]
        if (b2_con1a or b2_con1b) and b2_con2 and b2_con3:
            v1 = "二买"

        s2_con1a = len(cross) > 3 and cross[-1]["类型"] == "金叉" and cross[-1]["慢线"] < 0 and cross[-1]["距今"] > 5
        s2_con1b = len(cross) > 3 and cross[-1]["类型"] == "死叉" and up[-1]["慢线"] < 0 and cross[-1]["距今"] < 5
        s2_con2 = len(up) > 4 and up[-3]["慢线"] > 0 and up[-2]["慢线"] > 0
        s2_con3 = len(macd) > 10 and macd[-1] < macd[-2]
        if (s2_con1a or s2_con1b) and s2_con2 and s2_con3:
            v1 = "二卖"

        v2 = cross[-1]["类型"]

    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1, v2=v2)


def tas_macd_bs1_V230411(c: CZSC, **kwargs) -> OrderedDict:
    """基于MACD DIF的笔背驰判断信号

    参数模板："{freq}_D{di}T{tha}#{thb}#{thc}_BS1辅助V230411"

    **信号逻辑：**

    tha, thb, thc 分别为阈值，取值范围为 0 ~ 10000

    取5笔，从远到近分别记为 1、2、3、4、5，如果满足以下条件，则判断为顶背驰，反之为底背弛：

    1. 5向上，1~3的累计涨幅超过阈值tha，且3顶部的dif值大于1顶部dif值；
    2. 5的顶部相比于3的顶部的涨幅超过阈值-thb，且相应dif值的变化率小于阈值-thc；

    **信号列表：**

    - Signal('15分钟_D1T100#10#30_BS1辅助V230411_底背驰_任意_任意_0')
    - Signal('15分钟_D1T100#10#30_BS1辅助V230411_顶背驰_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典

        - di: 信号计算截止倒数第i根K线
        - tha: 前三笔的累计涨跌超过阈值tha，单位：BP，表示万分之一
        - thb: 第3笔相比第1笔的顶的涨跌幅阈值thb，单位：BP，表示万分之一
        - thc: 第5笔相比第3笔的DIF值的变化率阈值thc，单位：BP，表示万分之一

    :return: 返回信号结果
    """
    di = int(kwargs.get("di", 1))
    tha = int(kwargs.get("tha", 30))
    thb = int(kwargs.get("thb", 5))
    thc = int(kwargs.get("thc", 30))
    freq = c.freq.value
    assert 0 < tha < 10000, "tha 必须在 0 到 10000 之间"
    assert 0 < thb < 10000, "thb 必须在 0 到 10000 之间"
    assert 0 < thc < 10000, "thc 必须在 0 到 10000 之间"

    cache_key = update_macd_cache(c, fastperiod=12, slowperiod=26, signalperiod=9)
    k1, k2, k3 = f"{freq}_D{di}T{tha}#{thb}#{thc}_BS1辅助V230411".split("_")
    v1 = "其他"
    if len(c.bi_list) <= di + 7 or len(c.bars_ubi) > 9:
        # 笔数不够，或者当下未完成笔已经延伸超过9根K线，不计算
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bi1, bi2, bi3, bi4, bi5 = get_sub_elements(c.bi_list, di=di, n=5)
    # 第一个bar要有macd结果
    if np.isnan(bi1.raw_bars[0].cache[cache_key]["dif"]):
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    if bi5.direction == Direction.Up:
        bi1_dif = max([x.cache[cache_key]["dif"] for x in bi1.fx_b.raw_bars])
        bi3_dif = max([x.cache[cache_key]["dif"] for x in bi3.fx_b.raw_bars])
        bi5_dif = max([x.cache[cache_key]["dif"] for x in bi5.fx_b.raw_bars])

        # 前三笔累计涨幅超过阈值tha
        cond1 = ((bi3.high - bi1.low) / bi1.low) * 10000 > tha

        # 第二个向上笔的顶所对应的DIF值，要高于第一个向上笔的顶所对应的DIF值
        cond2 = bi3_dif > bi1_dif

        # 第三个向上笔的顶相比第二个向上笔的顶的涨幅超过阈值thb
        cond3 = ((bi5.high - bi3.high) / bi3.high) * 10000 > -thb

        # 第三个向上笔的顶相比第二个向上笔的顶的DIF值的变化率小于阈值thc
        cond4 = ((bi5_dif - bi3_dif) / bi3_dif) * 10000 < -thc

        if cond1 and cond2 and cond3 and cond4:
            v1 = "顶背驰"

    elif bi5.direction == Direction.Down:
        bi1_dif = min([x.cache[cache_key]["dif"] for x in bi1.fx_b.raw_bars])
        bi3_dif = min([x.cache[cache_key]["dif"] for x in bi3.fx_b.raw_bars])
        bi5_dif = min([x.cache[cache_key]["dif"] for x in bi5.fx_b.raw_bars])

        # 前三笔累计跌幅超过阈值tha
        cond1 = ((bi3.low - bi1.high) / bi1.high) * 10000 < -tha

        # 第二个向下笔的底所对应的DIF值，要小于第一个向下笔的底所对应的DIF值
        cond2 = bi3_dif < bi1_dif

        # 第三个向下笔的底相比第二个向下笔的底的跌幅小于thb
        cond3 = ((bi5.low - bi3.low) / bi3.low) * 10000 < thb

        # 第三个向下笔的底相比第二个向下笔的底的DIF值的变化率大于thc
        cond4 = ((bi5_dif - bi3_dif) / bi3_dif) * 10000 > thc

        if cond1 and cond2 and cond3 and cond4:
            v1 = "底背驰"

    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def tas_macd_bc_V240307(c: CZSC, **kwargs) -> OrderedDict:
    """MACD柱子辅助背驰判断

    参数模板："{freq}_D{di}N{n}柱子背驰_BS辅助V240307"

    **信号逻辑：**

    以顶背驰为例，最近N根K线的MACD柱子都大于0，且最近一个柱子高点小于前面的柱子高点，认为是顶背驰，做空；反之，做多。

    **信号列表：**

    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_底背驰_第1次_任意_0')
    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_底背驰_第2次_任意_0')
    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_底背驰_第3次_任意_0')
    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_顶背驰_第1次_任意_0')
    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_顶背驰_第2次_任意_0')
    - Signal('60分钟_D1N20柱子背驰_BS辅助V240307_顶背驰_第3次_任意_0')

    :param c: CZSC对象
    :param kwargs: 无
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 20))

    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}柱子背驰_BS辅助V240307".split("_")
    v1, v2 = "其他", "其他"
    cache_key = update_macd_cache(c)
    if len(c.bars_raw) < 7 + n:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    macd = [x.cache[cache_key]["macd"] for x in bars]
    n = len(macd)

    # 计算 MACD 柱子的顶和底序列
    gs = [i for i in range(1, n - 1) if macd[i - 1] < macd[i] > macd[i + 1] and macd[i] > 0]
    ds = [i for i in range(1, n - 1) if macd[i - 1] > macd[i] < macd[i + 1] and macd[i] < 0]

    if macd[-1] > 0 and len(gs) >= 2 and macd[gs[-1]] < macd[gs[-2]] and gs[-1] - gs[-2] > 2:
        macd_sub = macd[gs[-2] :]
        # 两个顶之间的柱子没有出现大的负值
        if abs(np.sum([x for x in macd_sub if x < 0])) < np.std(np.abs(macd_sub)):
            v1 = "顶背驰"
            v2 = f"第{n - gs[-1] - 1}次"

    if macd[-1] < 0 and len(ds) >= 2 and macd[ds[-1]] > macd[ds[-2]] and ds[-1] - ds[-2] > 2:
        macd_sub = macd[ds[-2] :]
        # 两个底之间的柱子没有出现大的正值
        if abs(np.sum([x for x in macd_sub if x > 0])) < np.std(np.abs(macd_sub)):
            v1 = "底背驰"
            v2 = f"第{n - ds[-1] - 1}次"

    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1, v2=v2)


def tas_dma_bs_V240608(c: CZSC, **kwargs) -> OrderedDict:
    """双均线多头排列下的回调买点

    参数模板："{freq}_N{n}双均线{t1}#{t2}顺势_BS辅助V240608"

    **信号逻辑：**

    参考链接：https://mp.weixin.qq.com/s/hR6wl3UrWvmLm1j5EABVyA

    买点的定位以均线为主，要求如下。
    1，做多的情况下5日均线和10日均线必须多头排列，做空的情况下5日均线和10日均线必须空头排列。
    2，以做多为例，做空反过来就是：日线价格回调到到5日均线或者10日均线。

    **信号列表：**

    - Signal('60分钟_N5双均线5#13顺势_BS辅助V240608_买点_任意_任意_0')
    - Signal('60分钟_N5双均线5#13顺势_BS辅助V240608_卖点_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 无

        - n: int, 默认5，取最近均线附近n个价格
        - t1: int, 默认5，均线1的周期
        - t2: int, 默认10，均线2的周期
    :return: 信号识别结果
    """
    n = int(kwargs.get("n", 5))
    t1 = int(kwargs.get("t1", 5))
    t2 = int(kwargs.get("t2", 10))

    assert t1 < t2, "均线1的周期必须小于均线2的周期"

    freq = c.freq.value
    k1, k2, k3 = f"{freq}_N{n}双均线{t1}#{t2}顺势_BS辅助V240608".split("_")
    v1 = "其他"
    ma1 = update_ma_cache(c, timeperiod=t1)
    ma2 = update_ma_cache(c, timeperiod=t2)
    if len(c.bars_raw) < 110:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = c.bars_raw[-100:]
    unique_prices = [x.close for x in bars] + [x.high for x in bars] + [x.low for x in bars] + [x.open for x in bars]
    unique_prices = sorted(list(set(unique_prices)))

    bar1, bar2 = bars[-2], bars[-1]
    ma1_value, ma2_value = bar2.cache[ma1], bar2.cache[ma2]
    lower_prices = [x for x in unique_prices if x < ma2_value]
    upper_prices = [x for x in unique_prices if x > ma2_value]

    if upper_prices and ma1_value > ma2_value and bar2.cache[ma2] > bar1.cache[ma2]:
        # ma2_round_high 是 ma2_value 上方的第 n 个价格
        ma2_round_high = upper_prices[n] if len(upper_prices) > n else upper_prices[-1]
        # 买点：1）上一根K线的最低价小于 ma2_round_high；2）当前K线的最高价大于 ma2_round_high，且收盘价小于 ma2_round_high
        if bar1.low < ma2_round_high < bar2.high and bar2.close < ma2_round_high:
            v1 = "买点"

    elif lower_prices and ma1_value < ma2_value and bar2.cache[ma2] < bar1.cache[ma2]:
        # ma2_round_low 是 ma2_value 下方的第 n 个价格
        ma2_round_low = lower_prices[-n] if len(lower_prices) > n else lower_prices[0]
        # 卖点：1）上一根K线的最高价大于 ma2_round_low；2）当前K线的收盘价大于 ma2_round_low，且收盘价大于 ma2_round_low
        if bar1.high > ma2_round_low > bar2.low and bar2.close > ma2_round_low:
            v1 = "卖点"

    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


# def tas_dif_zero_V240612(c: CZSC, **kwargs) -> OrderedDict:
#     """DIFF 远离零轴后靠近零轴，形成买卖点
#
#     参数模板："{freq}_DIF靠近零轴T{t}_BS辅助V240612"
#
#     **信号逻辑：**
#
#     买点的定位以DIF为主，要求如下。
#     1，取最近一个向下笔的底分型中的DIFF的最小值
#     2. 如果这个最小值在零轴的一个0.5倍标准差范围，那么就认为这个最小值是一个有效的买点
#
#     飞书文档：https://s0cqcxuy3p.feishu.cn/wiki/R9Y5w1w3Qi1jsHkzSyLcjoVWnld
#
#     **信号列表：**
#
#     - Signal('60分钟_DIF靠近零轴T50_BS辅助V240612_买点_任意_任意_0')
#     - Signal('60分钟_DIF靠近零轴T50_BS辅助V240612_卖点_任意_任意_0')
#
#     :param c: CZSC对象
#     :param kwargs: 无
#
#         - t: DIF波动率的倍数，除以100，默认为50
#
#     :return: 信号识别结果
#     """
#     t = int(kwargs.get("t", 50))  # 波动率的倍数，除以100
#
#     freq = c.freq.value
#     k1, k2, k3 = f"{freq}_DIF靠近零轴T{t}_BS辅助V240612".split("_")
#     v1 = "其他"
#     key = update_macd_cache(c)
#     if len(c.bars_raw) < 110 or len(c.bars_ubi) > 7:
#         return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
#
#     bi = c.bi_list[-1]
#     if len(bi.raw_bars) < 7:
#         return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
#
#     diffs = [x.cache[key]["dif"] for x in bi.raw_bars]
#     delta = np.std(diffs) * t / 100
#
#     if bi.direction == Direction.Down and delta > np.min(diffs) > -delta:
#         v1 = "买点"
#
#     if bi.direction == Direction.Up and -delta < np.max(diffs) < delta:
#         v1 = "卖点"
#
#     return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
