"""czsc 多级别共振策略：日线买卖点 × 周线末笔方向 × 周日线中枢共振。

决策规则（v1，确定性）：

- BUY：周日线中枢共振"看多"；或 日线买方向信号触发 且 周线末笔向上。
- SELL：周日线中枢共振"看空"；或 日线卖方向信号触发 且 周线末笔向下。

日线信号集默认含一/二/三类买卖点、方向明确的 N 笔形态、MACD/均线事件型
信号（见 _DEFAULT_SIGNALS，跨 signals_cxt 与 signals_tas 两模块解析），
可经 config.json 的 strategies[].params["signals"] 覆盖；信号值按 v1 段关键词
归类买/卖方向（_classify），无方向的结构值只进 snapshot、不参与触发。

同方向多条理由合并为一条告警；同一根 K 线同时得出 BUY 与 SELL 时视为信号
冲突，仅保留中枢共振一侧（结构级证据强于单级别买卖点），理由中标注反向证据。

周线经 resample_bars(drop_unfinished=False) 保留进行中的当周 K 线，避免周初
反转在周线维度滞后最多 4 个交易日（未完成周线语义与原版实时 BarGenerator 一致）。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..mcp_server.czsc_lite import CZSC, Freq, bars_from_df, resample_bars
from ..mcp_server.czsc_lite import signals_cxt as cxt
from ..mcp_server.czsc_lite import signals_tas as tas
from ..utils.global_vars import get_logger
from .alerts import Alert

STRATEGY_NAME = "czsc_resonance"

# 日线信号集（默认值，可经 params["signals"] 覆盖）：
# cxt 前 5 个为一/二/三类买卖点；cxt 后 5 个为方向明确的 N 笔形态与二类增强；
# tas 5 个为 MACD/均线事件型信号（背驰/金叉死叉买卖点/顺势回调）。
_DEFAULT_SIGNALS = (
    "cxt_first_buy_V221126",
    "cxt_first_sell_V221126",
    "cxt_second_bs_V230320",
    "cxt_third_buy_V230228",
    "cxt_third_bs_V230318",
    "cxt_second_bs_V240524",
    "cxt_five_bi_V230619",
    "cxt_seven_bi_V230620",
    "cxt_nine_bi_V230621",
    "cxt_eleven_bi_V230622",
    "tas_macd_first_bs_V221216",
    "tas_macd_second_bs_V221201",
    "tas_macd_bs1_V230411",
    "tas_macd_bc_V240307",
    "tas_dma_bs_V240608",
)
# 信号函数解析顺序：cxt 优先，tas 兜底（两模块无同名函数）。
_SIGNAL_SOURCES = (cxt, tas)
# 方向归类关键词：只匹配信号值的 v1 段（值格式 v1_v2_v3_score）。
# 颈线突破的方向语义源自五笔形态定义：上颈线突破出现在下跌五笔中（看多），下颈线对称；
# 买点/卖点来自 tas_dma_bs_V240608（双均线顺势回调）。
_BUY_KEYWORDS = ("一买", "二买", "三买", "底背驰", "上颈线突破", "买点")
_SELL_KEYWORDS = ("一卖", "二卖", "三卖", "顶背驰", "下颈线突破", "卖点")

logger = get_logger("strategy_czsc_resonance")


def _classify(value: str) -> Optional[str]:
    """信号值 → "BUY"/"SELL"/None（无方向的结构信号不参与触发）。"""
    v1 = str(value).split("_", 1)[0]
    if any(k in v1 for k in _BUY_KEYWORDS):
        return "BUY"
    if any(k in v1 for k in _SELL_KEYWORDS):
        return "SELL"
    return None


def _resolve_signal(name: str):
    """按 _SIGNAL_SOURCES 顺序解析信号函数名，未找到返回 None。"""
    for module in _SIGNAL_SOURCES:
        fn = getattr(module, name, None)
        if fn is not None:
            return fn
    return None


def _run_bs_signals(c: CZSC, signal_names: Tuple[str, ...], params: dict) -> Dict[str, str]:
    """运行日线买卖点信号，返回已触发（值非"其他"开头）的信号。"""
    fired = {}
    for name in signal_names:
        fn = _resolve_signal(name)
        if fn is None:
            continue
        try:
            sig = dict(fn(c, **params))
        except Exception as exc:
            logger.debug("信号 %s 计算失败: %s", name, exc)
            continue
        for k, v in sig.items():
            if not str(v).startswith("其他"):
                fired[k] = v
    return fired


def decide(
    daily_fired: Dict[str, str],
    weekly_direction: Optional[str],
    cross_value: str,
) -> List[Tuple[str, str]]:
    """纯决策函数：由信号快照得出 [(action, reason)]，便于确定性单测。

    BUY 与 SELL 同时成立时只保留中枢共振指向的一侧（共振是周日线结构级
    证据，强于单级别日线买卖点），并在理由中标注被压制的反向证据。
    """
    buy_hits = [f"{k}={v}" for k, v in daily_fired.items() if _classify(v) == "BUY"]
    sell_hits = [f"{k}={v}" for k, v in daily_fired.items() if _classify(v) == "SELL"]

    decisions: List[Tuple[str, str]] = []
    if cross_value.startswith("看多"):
        decisions.append(("BUY", "周日线中枢共振看多"))
    if buy_hits and weekly_direction == "向上":
        decisions.append(("BUY", f"日线买点({'; '.join(buy_hits)}) + 周线末笔向上"))
    if cross_value.startswith("看空"):
        decisions.append(("SELL", "周日线中枢共振看空"))
    if sell_hits and weekly_direction == "向下":
        decisions.append(("SELL", f"日线卖点({'; '.join(sell_hits)}) + 周线末笔向下"))

    merged: Dict[str, List[str]] = {}
    for action, reason in decisions:
        merged.setdefault(action, []).append(reason)

    if len(merged) > 1:
        # 冲突：共振方向裁决（共振触发时必属其一），保留该侧并标注反向证据
        keep = "BUY" if cross_value.startswith("看多") else "SELL"
        dropped = "SELL" if keep == "BUY" else "BUY"
        dropped_reasons = "；".join(merged.pop(dropped))
        merged[keep].append(f"[注意] 存在反向证据被共振压制: {dropped_reasons}")

    return [(action, "；".join(reasons)) for action, reasons in merged.items()]


def evaluate(symbol: str, daily_df: pd.DataFrame, params: dict | None = None) -> List[Alert]:
    """对单只股票执行一次共振评估，返回告警列表（可能为空）。

    Args:
        symbol: 股票代码（仅用于标注，数据来自 daily_df）。
        daily_df: 标准化日线 DataFrame。
        params: 信号配置：``signals`` 键覆盖日线信号集（函数名列表），
            其余键透传给各信号函数（如 di / ma_type / timeperiod）。
    """
    params = dict(params or {})
    signal_names = tuple(params.pop("signals", _DEFAULT_SIGNALS))
    c_daily = CZSC(bars_from_df(daily_df, Freq.D))
    # 保留进行中的当周，周线方向不滞后
    c_weekly = CZSC(resample_bars(daily_df, Freq.W, raw_bars=True, drop_unfinished=False))

    daily_fired = _run_bs_signals(c_daily, signal_names, params)
    weekly_direction = c_weekly.bi_list[-1].direction.value if c_weekly.bi_list else None
    cat = SimpleNamespace(kas={"周线": c_weekly, "日线": c_daily}, symbol=symbol)
    cross_sig = dict(cxt.cxt_zhong_shu_gong_zhen_V221221(cat, freq1="周线", freq2="日线"))
    cross_value = str(next(iter(cross_sig.values()))) if cross_sig else "其他"

    last_bar = c_daily.bars_raw[-1] if c_daily.bars_raw else None
    bar_dt = last_bar.dt.isoformat() if last_bar else ""
    snapshot = {
        "last_close": last_bar.close if last_bar else None,
        "daily_fired": daily_fired,
        "weekly_direction": weekly_direction,
        "cross_signal": cross_value,
    }
    now = datetime.now().isoformat()
    return [
        Alert(dt=now, symbol=symbol, strategy=STRATEGY_NAME, action=action,
              reason=reason, bar_dt=bar_dt, snapshot=snapshot)
        for action, reason in decide(daily_fired, weekly_direction, cross_value)
    ]
