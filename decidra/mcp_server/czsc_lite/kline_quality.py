# -*- coding: utf-8 -*-
"""K 线质量评估（源自 czsc.utils.kline_quality v0.9.69）。

与原版差异：移除 check_kline_quality 内的 print 输出——stdio 传输下 stdout
专供 MCP 协议，任何打印都会污染协议通道；另补充 summarize_kline_quality
返回 JSON 友好的问题摘要（不含 DataFrame）。
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]

# 日涨跌幅异常阈值（绝对值）
EXTREME_PCT_CHANGE_THRESHOLD = 0.2


def check_missing_values(df):
    """检查各列是否存在缺失值，并返回有缺失值的行。"""
    missing = df[df.isnull().any(axis=1)]
    if not missing.empty:
        return {"description": f"存在 {len(missing)} 条记录包含缺失值", "rows": missing}
    return {"description": "无缺失值", "rows": None}


def check_datetime_order(df):
    """检查日期时间是否升序排列、是否存在重复时间，并返回问题行。"""
    results = {}
    problem_rows = pd.DataFrame()

    if not df["dt"].is_monotonic_increasing:
        results["dt_order"] = "日期时间未按升序排列"
        sorted_df = df.sort_values("dt").reset_index(drop=True)
        mismatched = df[df["dt"].values != sorted_df["dt"].values]
        problem_rows = pd.concat([problem_rows, mismatched], ignore_index=True)
    else:
        results["dt_order"] = "日期时间按升序排列"

    duplicate_dt = df.duplicated(subset=["dt"]).sum()
    if duplicate_dt > 0:
        results["duplicate_dt"] = f"存在 {duplicate_dt} 个重复的日期时间"
        duplicates = df[df.duplicated(subset=["dt"], keep=False)]
        problem_rows = pd.concat([problem_rows, duplicates], ignore_index=True)
    else:
        results["duplicate_dt"] = "无重复的日期时间"

    if not problem_rows.empty:
        return {"description": results, "rows": problem_rows.drop_duplicates()}
    return {"description": results, "rows": None}


def check_price_reasonableness(df):
    """检查价格数据的合理性（high/low 覆盖 open/close、非负非零），返回问题行。"""
    issues = {}
    problem_rows = pd.DataFrame()

    invalid_high = df[df["high"] < df[["open", "close"]].max(axis=1)]
    if not invalid_high.empty:
        issues["high_less_than_open_close"] = f"存在 {len(invalid_high)} 条记录，'high' 小于 'open' 或 'close'"
        problem_rows = pd.concat([problem_rows, invalid_high], ignore_index=True)

    invalid_low = df[df["low"] > df[["open", "close"]].min(axis=1)]
    if not invalid_low.empty:
        issues["low_greater_than_open_close"] = f"存在 {len(invalid_low)} 条记录，'low' 大于 'open' 或 'close'"
        problem_rows = pd.concat([problem_rows, invalid_low], ignore_index=True)

    negative_prices = df[(df[["open", "close", "high", "low"]] <= 0).any(axis=1)]
    if not negative_prices.empty:
        issues["negative_prices"] = f"存在 {len(negative_prices)} 条记录，价格为负数或零"
        problem_rows = pd.concat([problem_rows, negative_prices], ignore_index=True)

    if issues:
        return {"description": issues, "rows": problem_rows.drop_duplicates()}
    return {"description": "所有价格数据合理", "rows": None}


def check_volume_amount(df):
    """检查成交量和金额的合理性（非负、vol 为零时 amount 应为零），返回问题行。"""
    issues = {}
    problem_rows = pd.DataFrame()

    negative_vol = df[df["vol"] < 0]
    if not negative_vol.empty:
        issues["negative_vol"] = f"存在 {len(negative_vol)} 条记录，'vol' 为负数"
        problem_rows = pd.concat([problem_rows, negative_vol], ignore_index=True)

    negative_amount = df[df["amount"] < 0]
    if not negative_amount.empty:
        issues["negative_amount"] = f"存在 {len(negative_amount)} 条记录，'amount' 为负数"
        problem_rows = pd.concat([problem_rows, negative_amount], ignore_index=True)

    zero_vol_nonzero_amount = df[(df["vol"] == 0) & (df["amount"] != 0)]
    if not zero_vol_nonzero_amount.empty:
        issues["zero_vol_nonzero_amount"] = (
            f"存在 {len(zero_vol_nonzero_amount)} 条记录，'vol' 为零但 'amount' 不为零"
        )
        problem_rows = pd.concat([problem_rows, zero_vol_nonzero_amount], ignore_index=True)

    if issues:
        return {"description": issues, "rows": problem_rows.drop_duplicates()}
    return {"description": "成交量和金额数据合理", "rows": None}


def check_symbol_consistency(df):
    """检查符号数据的一致性和有效性（非空字符串），返回问题行。"""
    invalid_symbols = df[df["symbol"].isnull() | (df["symbol"].astype(str).str.strip() == "")]
    if not invalid_symbols.empty:
        return {"description": f"存在 {len(invalid_symbols)} 条记录，符号为空或无效", "rows": invalid_symbols}
    return {"description": "符号数据一致且有效", "rows": None}


def check_duplicate_records(df):
    """检查是否存在完全重复的记录，返回重复行。"""
    duplicate_records = df[df.duplicated()]
    if not duplicate_records.empty:
        return {"description": f"存在 {len(duplicate_records)} 条完全重复的记录", "rows": duplicate_records}
    return {"description": "无重复记录", "rows": None}


def check_extreme_values(df, threshold: float = EXTREME_PCT_CHANGE_THRESHOLD):
    """检查相邻收盘价涨跌幅是否超过阈值（绝对值），返回问题行。"""
    if "close" not in df.columns:
        return {"description": "缺少 'close' 列，无法进行异常值检查", "rows": None}

    df = df.copy()
    df["pct_change"] = df["close"].pct_change().abs()
    extreme_changes = df[df["pct_change"] > threshold]
    if not extreme_changes.empty:
        return {
            "description": f"存在 {len(extreme_changes)} 条记录，价格涨跌幅超过 {threshold * 100}%",
            "rows": extreme_changes,
        }
    return {"description": "无异常的价格涨跌幅", "rows": None}


def check_kline_quality(df: pd.DataFrame) -> dict:
    """检查 K 线数据的质量问题，按 symbol 返回各检查点结果（不打印）。

    :param df: 必须包含列 REQUIRED_COLUMNS
    :return: {symbol: {检查点: {'description': ..., 'rows': DataFrame|None}}}
    """
    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_columns:
        raise ValueError(f"输入数据缺少必要的列: {missing_columns}")

    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["dt"]):
        df["dt"] = pd.to_datetime(df["dt"], errors="coerce")

    quality_issues = {}
    for symbol, group in df.groupby("symbol"):
        group_sorted = group.sort_values("dt").reset_index(drop=True)
        quality_issues[symbol] = {
            "missing_values": check_missing_values(group_sorted),
            "datetime_order": check_datetime_order(group_sorted),
            "price_reasonableness": check_price_reasonableness(group_sorted),
            "volume_amount": check_volume_amount(group_sorted),
            "symbol_consistency": check_symbol_consistency(group_sorted),
            "duplicate_records": check_duplicate_records(group_sorted),
            "extreme_values": check_extreme_values(group_sorted),
        }
    return quality_issues


def summarize_kline_quality(df: pd.DataFrame) -> List[str]:
    """K 线质量问题摘要（仅问题描述，JSON 友好，无问题时为空列表）。"""
    issues = []
    for symbol, symbol_issues in check_kline_quality(df).items():
        for check, result in symbol_issues.items():
            if result["rows"] is not None:
                issues.append(f"{symbol} {check}: {result['description']}")
    return issues
