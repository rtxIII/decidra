"""策略 Runner：cron 冷启动执行一轮扫描并落盘告警。

用法::

    python -m decidra.strategy.runner run           # 执行一轮扫描
    python -m decidra.strategy.runner install-cron  # 按配置注册/更新 cron job

cron 调度器由 monitor 托管启停（见 monitor/terminal/cron_daemon.py）；本模块
只负责单轮"取数 → 评估 → 去重 → 落盘"，状态经 ~/.decidra/.runtime/strategy/
文件传递，进程退出无残留。cron 表达式按 UTC 语义解释。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..utils.global_vars import PATH_OPENHARNESS, PATH_STRATEGY_RUNTIME, get_logger
from . import czsc_resonance
from .alerts import ALERTS_PATH, DEDUPE_STATE_PATH, DedupeState, append_alerts
from .config import load_config

logger = get_logger("strategy_runner")

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
# 与 runtime_bridge / cron_daemon 一致的 openharness 配置目录（定义于 global_vars）
OPENHARNESS_CONFIG_DIR: Path = PATH_OPENHARNESS
# 按 symbol 的日线增量缓存目录
KLINE_CACHE_DIR: Path = PATH_STRATEGY_RUNTIME / "kline_cache"

# 策略注册表：name → evaluate(symbol, daily_df, params) -> List[Alert]
_STRATEGY_REGISTRY = {
    czsc_resonance.STRATEGY_NAME: czsc_resonance.evaluate,
}


def fetch_daily_df(fm, symbol: str, days: int):
    """富途取日线并标准化为 czsc 列，附 K 线质量检查（问题记日志）。

    增量缓存：按 symbol 落盘 parquet（``kline_cache/``），命中时只向富途请求
    缓存末日之后的区间；最后一根缓存 K 线（当日可能未收盘）总是丢弃重取。
    """
    import pandas as pd

    from ..mcp_server.czsc_lite import summarize_kline_quality

    end = date.today()
    start = end - timedelta(days=days)
    cache_path = KLINE_CACHE_DIR / f"{symbol.replace('.', '_')}_day.parquet"

    cached = None
    fetch_start = start
    if cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
            cached = cached[cached["dt"] >= pd.Timestamp(start)]
            if len(cached) > 1:
                # 丢弃缓存末根（写入时可能未收盘），从其当日起重取
                cached = cached.iloc[:-1]
                fetch_start = cached["dt"].iloc[-1].date() + timedelta(days=1)
            else:
                cached = None
        except Exception as exc:
            logger.warning("K线缓存读取失败 %s，全量重取: %s", symbol, exc)
            cached = None

    df = fm.request_history_kline(symbol, start=str(fetch_start), end=str(end), ktype="K_DAY")
    if (df is None or df.empty) and cached is None:
        raise ValueError(f"未取到 {symbol} 的 K 线数据")

    if df is not None and not df.empty:
        fresh = pd.DataFrame({
            "symbol": symbol,
            "dt": pd.to_datetime(df["time_key"]),
            "open": df["open"].astype(float),
            "close": df["close"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "vol": df["volume"].astype(float),
            "amount": df["turnover"].astype(float),
        })
        std = pd.concat([cached, fresh], ignore_index=True) if cached is not None else fresh
    else:
        std = cached.reset_index(drop=True)

    std = std.drop_duplicates(subset=["dt"], keep="last").sort_values("dt").reset_index(drop=True)

    try:
        KLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        std.to_parquet(cache_path, index=False)
    except Exception as exc:
        logger.warning("K线缓存写入失败 %s: %s", symbol, exc)

    issues = summarize_kline_quality(std)
    if issues:
        logger.warning("K线质量问题 %s: %s", symbol, issues)
    return std


def run_scan(
    config: Optional[dict] = None,
    fetch_fn: Optional[Callable] = None,
    alerts_path: Path = ALERTS_PATH,
    state_path: Path = DEDUPE_STATE_PATH,
) -> dict:
    """执行一轮策略扫描。

    Args:
        config: 策略配置，缺省读 ~/.decidra/strategy/config.json。
        fetch_fn: ``(symbol, days) -> DataFrame``，缺省走富途取数；测试可注入合成数据源。
        alerts_path / state_path: 告警与去重状态文件路径（测试可指向临时目录）。

    Returns:
        扫描摘要 {scanned, alerts, suppressed, errors}。
    """
    config = config or load_config()
    watchlist = config.get("watchlist", [])
    days = int(config.get("kline_days", 730))
    enabled = [s for s in config.get("strategies", []) if s.get("enabled", True)]

    fm = None
    if fetch_fn is None:
        from ..modules.futu_market import FutuMarket

        try:
            fm = FutuMarket()
            fm.open()
        except Exception as exc:
            # OpenD 未运行等连接失败：整轮降级为取数错误，而非崩溃
            logger.error("富途连接失败，跳过本轮扫描: %s", exc)
            return {
                "scanned": len(watchlist),
                "alerts": 0,
                "suppressed": 0,
                "errors": {"futu_connection": str(exc)},
            }

        def fetch_fn(symbol: str, days: int):  # noqa: F811
            return fetch_daily_df(fm, symbol, days)

    state = DedupeState(state_path)
    fired, suppressed, errors = [], 0, {}
    try:
        for symbol in watchlist:
            try:
                df = fetch_fn(symbol, days)
            except Exception as exc:
                errors[symbol] = str(exc)
                logger.error("取数失败 %s: %s", symbol, exc)
                continue
            for item in enabled:
                evaluate = _STRATEGY_REGISTRY.get(item.get("name"))
                if evaluate is None:
                    errors[str(item.get("name"))] = "未注册的策略"
                    continue
                try:
                    alerts = evaluate(symbol, df, item.get("params") or {})
                except Exception as exc:
                    errors[f"{symbol}:{item.get('name')}"] = str(exc)
                    logger.error("策略评估失败 %s/%s: %s", symbol, item.get("name"), exc)
                    continue
                for alert in alerts:
                    if state.should_fire(alert.symbol, alert.strategy, alert.action, alert.bar_dt):
                        fired.append(alert)
                        state.mark(alert.symbol, alert.strategy, alert.action, alert.bar_dt)
                    else:
                        suppressed += 1
    finally:
        if fm is not None:
            fm.close()

    append_alerts(fired, alerts_path)
    state.save()
    summary = {
        "scanned": len(watchlist),
        "alerts": len(fired),
        "suppressed": suppressed,
        "errors": errors,
    }
    logger.info("策略扫描完成: %s", summary)
    return summary


def install_cron(config: Optional[dict] = None) -> dict:
    """按配置注册/更新策略扫描 cron job（表达式按 UTC 语义）。"""
    os.environ.setdefault("OPENHARNESS_CONFIG_DIR", str(OPENHARNESS_CONFIG_DIR))
    from openharness.services.cron import upsert_cron_job, validate_cron_expression

    config = config or load_config()
    cron_cfg = config.get("cron", {})
    name = cron_cfg.get("name", "decidra_strategy_scan")
    schedule = cron_cfg.get("schedule", "*/15 * * * *")
    if not validate_cron_expression(schedule):
        raise ValueError(f"非法 cron 表达式: {schedule!r}（5 段格式，UTC 语义）")

    job = {
        "name": name,
        "schedule": schedule,
        "command": f'"{sys.executable}" -m decidra.strategy.runner run',
        "cwd": str(REPO_ROOT),
        "enabled": True,
    }
    upsert_cron_job(job)
    return job


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Decidra 策略 Runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="执行一轮策略扫描")
    sub.add_parser("install-cron", help="按配置注册/更新策略扫描 cron job（UTC 表达式）")
    args = parser.parse_args(argv)

    if args.command == "run":
        summary = run_scan()
        print(json.dumps(summary, ensure_ascii=False))
    else:
        job = install_cron()
        print(f"cron job '{job['name']}' [{job['schedule']}] 已写入注册表（UTC 语义）")


if __name__ == "__main__":
    main()
