"""czsc_lite —— 从 czsc 裁剪 fork 的缠论信号分析核心（零重依赖）。

来源: https://github.com/waditu/czsc (v0.9.69)，作者 zengbin93。仅 fork 缠论结构分析
与信号计算所需的最小闭包（enum / objects / analyze / sig / ta / signals_cxt），
不引入 czsc 的看板(streamlit)/存储(oss2/clickhouse)/绘图(matplotlib/lightweight-charts)
等重依赖。talib 被本地纯 numpy 的 ta 实现替代。

依赖仅 numpy / pandas / scikit-learn（均已随 Decidra 安装）。

用法::

    from decidra.mcp_server.czsc_lite import CZSC, RawBar, Freq
    c = CZSC(bars)                      # bars: List[RawBar]
    from decidra.mcp_server.czsc_lite import signals_cxt
    sig = signals_cxt.cxt_bi_end_V230618(c)
"""

from .analyze import CZSC
from .objects import RawBar, NewBar, BI, FX, ZS, Signal
from .enum import Freq, Mark, Direction, Operate

__all__ = ["CZSC", "RawBar", "NewBar", "BI", "FX", "ZS", "Signal", "Freq", "Mark", "Direction", "Operate"]
