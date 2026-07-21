"""告警/研判结果回收与评测（enrich-evals）。

给每条 BUY/SELL 告警在 T+N 交易日回填**前向收益**与**方向是否命中**，落
``outcomes.json``；联立 ``enrichments.json`` 产出滚动命中率、AI 研判增量价值
与置信度校准。评测对 alerts/enrichments 只读，回填失败不影响告警产出与研判落盘。

取数（免 FutuOpenD，跨 HK/US/A）：富途码经市场路由——A 股（``SH.``/``SZ.``）
走 ``backtest.loader.FetcherLoader``（Tdx 链），港美股（``HK.``/``US.``）经
``yfinance`` 直取（``yf.Ticker(...).history``，绕开只认 A 股码的 fetcher 转换）。
**同源定价**：``priced_from`` / ``priced_to`` 均取自同一次取数，``snapshot.last_close``
仅在取数帧缺锚日时兜底，规避跨源基差。

用法::

    python -m decidra.strategy.evals backfill [--horizon N]
    python -m decidra.strategy.evals report   [--window D]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

from ..utils.global_vars import PATH_STRATEGY_RUNTIME, get_logger
from .alerts import ALERTS_PATH, load_enrichments, read_all_alerts
from .config import load_config

logger = get_logger("strategy_evals")

OUTCOMES_PATH: Path = PATH_STRATEGY_RUNTIME / "outcomes.json"

# 前向方向判定与置信度分桶
_DIRECTIONAL_ACTIONS = ("BUY", "SELL")
_CONFIDENCE_LEVELS = ("高", "中", "低")
_SUPPORT = "支持"
_OPPOSE = "反对"
# 度量样本不足此阈值时返回 null（避免误导性数值）
MIN_REPORT_SAMPLE = 5

# fetch_closes_fn 契约：(futu_symbol, anchor_dt_iso, now) -> 收盘价 Series 或 None
FetchClosesFn = Callable[[str, str, datetime], Optional[Any]]


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


# ─── outcomes.json 读写（与 enrichments.json 同并发约定）───


def load_outcomes(path: Path = OUTCOMES_PATH) -> Dict[str, dict]:
    """读取全部回填结果（alert_id → outcome），文件不存在/损坏返回空字典。"""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_outcomes(outcomes: Dict[str, dict], path: Path = OUTCOMES_PATH) -> None:
    """锁内合并盘上最新结果后原子写回（与并发写者互不丢更新）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(_lock_path(path)):
        merged = load_outcomes(path)
        merged.update(outcomes)
        atomic_write_text(
            path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        )


# ─── 富途码 → 市场路由 + fetcher 码 ───


def _to_market_and_code(futu_symbol: str) -> Tuple[str, str]:
    """富途码 → (市场, fetcher 码)。

    ``SH.600000`` → ("a", "600000")；``HK.00700`` → ("hk", "0700.HK")；
    ``US.AAPL`` → ("us", "AAPL")。无法识别前缀时抛错。
    """
    symbol = (futu_symbol or "").strip()
    if symbol.startswith(("SH.", "SZ.")):
        return "a", symbol.split(".", 1)[1]
    if symbol.startswith("HK."):
        digits = symbol.split(".", 1)[1]
        # 富途 HK 为 5 位零填充，yfinance 用去零后至少 4 位（0700.HK / 9988.HK）
        return "hk", f"{int(digits):04d}.HK"
    if symbol.startswith("US."):
        return "us", symbol.split(".", 1)[1]
    raise ValueError(f"无法识别市场（需 SH./SZ./HK./US. 前缀）: {futu_symbol!r}")


def _default_fetch_closes(
    futu_symbol: str, anchor_dt: str, now: datetime
) -> Optional[Any]:
    """按市场路由取 [锚日, now] 的日线收盘价 Series（DatetimeIndex 升序）。

    A 股走 FetcherLoader（Tdx 链）；港美股 yfinance 直取。取不到返回 None。
    重依赖（pandas/yfinance/FetcherLoader）延迟导入，保持模块导入期轻量。
    """
    import pandas as pd

    market, code = _to_market_and_code(futu_symbol)
    start_date = pd.Timestamp(anchor_dt).normalize().date()

    if market == "a":
        from .backtest.loader import FetcherLoader

        data_map = FetcherLoader().fetch([code], str(start_date), str(now.date()))
        df = data_map.get(code)
        if df is None or df.empty or "close" not in df.columns:
            return None
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        return closes if len(closes) else None

    import yfinance as yf

    # yfinance end 为开区间，+1 日以包含 now 当日
    end_exclusive = now.date() + timedelta(days=1)
    raw = yf.Ticker(code).history(
        start=str(start_date), end=str(end_exclusive), interval="1d"
    )
    if raw is None or raw.empty or "Close" not in raw.columns:
        return None
    index = raw.index
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    closes = pd.Series(
        pd.to_numeric(raw["Close"], errors="coerce").values,
        index=index.normalize(),
    ).dropna()
    return closes if len(closes) else None


# ─── 前向定价（纯函数，可无网络测试）───


def _forward_from_closes(
    closes: Any, anchor_ts: Any, horizon_days: int
) -> Optional[Tuple[Optional[float], float, str]]:
    """由收盘价 Series 定位锚后第 N 根日线。

    Args:
        closes: DatetimeIndex（升序）→ 收盘价的 Series。
        anchor_ts: 锚点时间戳（pandas Timestamp）。
        horizon_days: 前向 K 线根数 N。

    Returns:
        ``(priced_from, priced_to, priced_to_dt_iso)``——priced_from 为取数帧内
        锚日收盘价（缺锚日时 None，由调用方以 snapshot 兜底）；不足 N 根后续
        日线时返回 None（pending）。
    """
    anchor_day = anchor_ts.normalize()
    index_days = closes.index.normalize()
    after = closes[index_days > anchor_day]
    if len(after) < horizon_days:
        return None
    priced_to = float(after.iloc[horizon_days - 1])
    priced_to_dt = after.index[horizon_days - 1]
    same_day = closes[index_days == anchor_day]
    priced_from = float(same_day.iloc[-1]) if len(same_day) else None
    return priced_from, priced_to, priced_to_dt.isoformat()


def _as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # NaN → None


# ─── 回填 ───


def backfill(
    horizon_days: Optional[int] = None,
    now: Optional[datetime] = None,
    *,
    config: Optional[dict] = None,
    alerts_path: Path = ALERTS_PATH,
    outcomes_path: Path = OUTCOMES_PATH,
    fetch_closes_fn: Optional[FetchClosesFn] = None,
) -> dict:
    """回填告警前向结果。

    扫描 ``alerts.jsonl`` 中锚后已有 ≥N 根后续日线且无 outcome 的 BUY/SELL，
    取后续日线算前向收益（BUY：``close(锚+N)/close(锚)-1``；SELL 取反号，跌为
    命中），写 ``outcomes.json``。单条取数失败/未到期隔离，不整批中断、不落伪结果。

    Args:
        horizon_days: 前向 K 线根数，缺省读配置 ``evals.horizon_days``。
        now: 当前时间（测试可注入），缺省 ``datetime.now()``。
        config: 策略配置，缺省 ``load_config()``。
        alerts_path / outcomes_path: 告警与结果文件路径（测试可指向临时目录）。
        fetch_closes_fn: ``(symbol, anchor_dt, now) -> Series | None`` 取数注入点，
            缺省走真实路由取数；测试注入合成收盘价源。

    Returns:
        回填摘要 {priced, pending, skipped, errors, total_outcomes}。
    """
    import pandas as pd

    config = config or load_config()
    evals_config = config.get("evals") or {}
    horizon = int(
        horizon_days if horizon_days is not None
        else evals_config.get("horizon_days", 5)
    )
    now = now or datetime.now()
    fetch_closes = fetch_closes_fn or _default_fetch_closes

    outcomes = load_outcomes(outcomes_path)
    new_outcomes: Dict[str, dict] = {}
    priced = pending = skipped = 0
    errors: Dict[str, str] = {}

    # 收集待回填候选（跳过已回填/非方向/无效锚），供按标的合批取数
    candidates: List[Tuple[dict, str, str, str, str, Any]] = []
    for alert in read_all_alerts(alerts_path):
        alert_id = alert.get("id")
        if not alert_id or alert_id in outcomes:
            continue
        action = alert.get("action")
        if action not in _DIRECTIONAL_ACTIONS:
            continue
        anchor_dt = alert.get("bar_dt") or ""
        symbol = alert.get("symbol") or ""
        if not anchor_dt or not symbol:
            skipped += 1
            continue
        try:
            anchor_ts = pd.Timestamp(anchor_dt)
        except (ValueError, TypeError):
            skipped += 1  # bar_dt 非法（我方产出恒为合法 ISO，此为边界防护）
            continue
        candidates.append((alert, alert_id, action, symbol, anchor_dt, anchor_ts))

    # 按锚点升序：每个标的首次遇到时以其最早锚取一次 [最早锚, now]，覆盖该标的
    # 全部候选（同标的数十条告警只取一次数，_forward_from_closes 按锚切片复用）。
    candidates.sort(key=lambda item: item[5])
    closes_cache: Dict[str, Optional[Any]] = {}
    failed_symbols: Dict[str, str] = {}

    for alert, alert_id, action, symbol, anchor_dt, anchor_ts in candidates:
        if symbol in failed_symbols:
            errors[alert_id] = failed_symbols[symbol]
            continue
        if symbol not in closes_cache:
            try:
                closes_cache[symbol] = fetch_closes(symbol, anchor_dt, now)
            except Exception as exc:
                failed_symbols[symbol] = str(exc)
                errors[alert_id] = str(exc)
                logger.warning("评测取数失败 %s(%s): %s", symbol, alert_id, exc)
                continue
        closes = closes_cache[symbol]
        if closes is None or len(closes) == 0:
            pending += 1
            continue

        forward = _forward_from_closes(closes, anchor_ts, horizon)
        if forward is None:
            pending += 1  # 锚后不足 N 根，等下轮
            continue
        priced_from_src, priced_to, priced_to_dt = forward

        snapshot_close = (alert.get("snapshot") or {}).get("last_close")
        anchor_close = (
            priced_from_src if priced_from_src is not None
            else _as_float(snapshot_close)
        )
        if anchor_close is None or anchor_close <= 0:
            skipped += 1  # 锚日无价，无法定价
            continue

        raw_return = priced_to / anchor_close - 1.0
        forward_return = raw_return if action == "BUY" else -raw_return
        new_outcomes[alert_id] = {
            "symbol": symbol,
            "action": action,
            "bar_dt": anchor_dt,
            "horizon_days": horizon,
            "priced_from": round(anchor_close, 6),
            "priced_to": round(priced_to, 6),
            "priced_to_dt": priced_to_dt,
            "forward_return": round(forward_return, 6),
            "direction_correct": bool(forward_return > 0),
            "priced_at": now.isoformat(timespec="seconds"),
        }
        priced += 1

    if new_outcomes:
        save_outcomes(new_outcomes, outcomes_path)

    summary = {
        "priced": priced,
        "pending": pending,
        "skipped": skipped,
        "errors": errors,
        "total_outcomes": len(outcomes) + len(new_outcomes),
    }
    logger.info("评测回填完成: %s", summary)
    return summary


# ─── 报告 ───


def _within_window(bar_dt: str, cutoff: datetime) -> bool:
    if not bar_dt:
        return False
    try:
        return datetime.fromisoformat(bar_dt) >= cutoff
    except ValueError:
        return False


def _rate_result(
    flags: List[bool], min_sample: int = MIN_REPORT_SAMPLE
) -> Dict[str, Any]:
    """命中率 + 样本数；样本不足 min_sample 时 rate 为 null。

    聚合度量用默认阈值（避免误导性数值）；按标的钻取用 min_sample=1（n 随行
    展示，由读者按样本量自行判断）。
    """
    n = len(flags)
    if n < min_sample:
        return {"rate": None, "n": n}
    return {"rate": round(sum(1 for flag in flags if flag) / n, 4), "n": n}


def _mean_result(
    values: List[float], min_sample: int = MIN_REPORT_SAMPLE
) -> Dict[str, Any]:
    n = len(values)
    if n < min_sample:
        return {"avg": None, "n": n}
    return {"avg": round(sum(values) / n, 6), "n": n}


def report(
    window: Optional[int] = None,
    now: Optional[datetime] = None,
    *,
    config: Optional[dict] = None,
    outcomes_path: Path = OUTCOMES_PATH,
    enrichments_path: Optional[Path] = None,
) -> dict:
    """联立 outcomes × enrichments 产出 §4 度量（滚动窗口，样本不足返 null）。

    ``signal_hit_rate`` / ``avg_forward_return`` 覆盖全量告警（按
    ``(symbol, action, bar_dt)`` 去重，规避"转正"同锚双计）；``enriched_hit_rate``
    / ``veto_avoid_rate`` / ``confidence_calibration`` 仅覆盖人工研判过的告警。
    """
    config = config or load_config()
    evals_config = config.get("evals") or {}
    window = int(
        window if window is not None else evals_config.get("report_window", 90)
    )
    now = now or datetime.now()
    cutoff = now - timedelta(days=window)

    outcomes = load_outcomes(outcomes_path)
    enrichments = load_enrichments(enrichments_path)

    # 全量信号级：按 (symbol, action, bar_dt) 去重
    deduped: List[dict] = []
    seen = set()
    for outcome in outcomes.values():
        bar_dt = outcome.get("bar_dt", "")
        if not _within_window(bar_dt, cutoff):
            continue
        key = (outcome.get("symbol"), outcome.get("action"), bar_dt)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(outcome)

    signal_hit = _rate_result([bool(o.get("direction_correct")) for o in deduped])
    avg_forward_return = {
        action: _mean_result(
            [float(o.get("forward_return", 0.0))
             for o in deduped if o.get("action") == action]
        )
        for action in _DIRECTIONAL_ACTIONS
    }

    # 按标的钻取（(symbol, action) 分组，样本天然小故 min_sample=1、始终展示 + 附 n）
    symbol_groups: Dict[Tuple[str, str], List[dict]] = {}
    for outcome in deduped:
        symbol_groups.setdefault(
            (outcome.get("symbol"), outcome.get("action")), []
        ).append(outcome)
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for (symbol, action), rows in symbol_groups.items():
        by_symbol.setdefault(symbol, {})[action] = {
            "hit_rate": _rate_result(
                [bool(r.get("direction_correct")) for r in rows], min_sample=1
            ),
            "avg_forward_return": _mean_result(
                [float(r.get("forward_return", 0.0)) for r in rows], min_sample=1
            ),
        }

    # AI 增量：研判过且有 outcome 的告警（alert_id 级，逐条人工判断不去重）
    enriched: List[Tuple[dict, dict]] = []
    for alert_id, enrichment in enrichments.items():
        outcome = outcomes.get(alert_id)
        if outcome is None or not _within_window(outcome.get("bar_dt", ""), cutoff):
            continue
        enriched.append((outcome, enrichment))

    support_flags = [
        bool(o.get("direction_correct"))
        for o, e in enriched if e.get("conclusion") == _SUPPORT
    ]
    # 反对且事后确属坏信号（未命中）→ AI 成功规避
    veto_flags = [
        not bool(o.get("direction_correct"))
        for o, e in enriched if e.get("conclusion") == _OPPOSE
    ]
    calibration = {
        level: _rate_result([
            bool(o.get("direction_correct"))
            for o, e in enriched if e.get("confidence") == level
        ])
        for level in _CONFIDENCE_LEVELS
    }

    return {
        "window_days": window,
        "horizon_days": int(evals_config.get("horizon_days", 5)),
        "as_of": now.isoformat(timespec="seconds"),
        "signal_hit_rate": signal_hit,
        "avg_forward_return": avg_forward_return,
        "by_symbol": by_symbol,
        "enriched_hit_rate": _rate_result(support_flags),
        "veto_avoid_rate": _rate_result(veto_flags),
        "confidence_calibration": calibration,
        "total_outcomes": len(outcomes),
        "note": (
            "前向收益为收盘→收盘纸面收益（非可成交）；AI 增量三项仅覆盖人工研判过的"
            "告警，样本不足时 rate=null"
        ),
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Decidra 告警/研判结果回收与评测")
    sub = parser.add_subparsers(dest="command", required=True)
    backfill_parser = sub.add_parser("backfill", help="回填告警前向结果")
    backfill_parser.add_argument(
        "--horizon", type=int, default=None,
        help="前向 K 线根数（缺省读配置 evals.horizon_days）",
    )
    report_parser = sub.add_parser("report", help="打印滚动评测报告")
    report_parser.add_argument(
        "--window", type=int, default=None,
        help="滚动报告窗口自然日（缺省读配置 evals.report_window）",
    )
    args = parser.parse_args(argv)

    if args.command == "backfill":
        result = backfill(horizon_days=args.horizon)
    else:
        result = report(window=args.window)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
