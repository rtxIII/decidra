"""策略信息的终端展示：Rich markup 文本，供 monitor 终端面板播报。

告警块与启动概况都是纯函数产出字符串，不依赖 Textual，便于单测。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from ..utils.global_vars import PATH_OPENHARNESS_DATA
from .alerts import ALERTS_PATH, load_enrichments, read_recent_alerts
from .config import load_config

# 与 runtime_bridge / cron_daemon 一致的 openharness 数据目录（定义于 global_vars）
OPENHARNESS_DATA_DIR: Path = PATH_OPENHARNESS_DATA
CRON_JOBS_PATH: Path = OPENHARNESS_DATA_DIR / "cron_jobs.json"
CRON_HISTORY_PATH: Path = OPENHARNESS_DATA_DIR / "cron_history.jsonl"

_ACTION_MARKUP = {
    "BUY": "[bold green]▲ BUY[/]",
    "SELL": "[bold red]▼ SELL[/]",
}


def _fmt_dt(value, length: int = 19) -> str:
    return str(value or "")[:length].replace("T", " ")


_CONCLUSION_COLORS = {"支持": "green", "反对": "red", "观望": "yellow"}


def format_alert(alert: dict, enrichment: Optional[dict] = None) -> str:
    """单条告警的终端富文本块（多行）；带 enrichment 时展示研判结论。"""
    action = str(alert.get("action", "?"))
    action_markup = _ACTION_MARKUP.get(action, f"[bold]{action}[/]")
    alert_id = alert.get("id") or ""
    id_part = f"[dim]#{alert_id}[/] " if alert_id else ""

    snapshot = alert.get("snapshot") or {}
    last_close = snapshot.get("last_close")
    close_part = f" @{last_close}" if last_close is not None else ""
    daily_fired = snapshot.get("daily_fired") or {}
    daily_part = "、".join(str(v).split("_")[0] for v in daily_fired.values()) or "无"
    weekly = snapshot.get("weekly_direction") or "未知"
    cross = str(snapshot.get("cross_signal", "其他")).split("_")[0]

    details = [
        f"理由: {alert.get('reason', '')}",
        f"周线 {weekly} ｜ 共振 {cross} ｜ 日线买卖点 {daily_part}"
        f" ｜ 策略 [dim]{alert.get('strategy', '')}[/]",
    ]
    if enrichment:
        conclusion = str(enrichment.get("conclusion", "?"))
        color = _CONCLUSION_COLORS.get(conclusion, "white")
        details.append(
            f"研判: [{color}]{conclusion}[/]（置信度 {enrichment.get('confidence', '中')}）"
            f" {enrichment.get('summary', '')}"
        )

    lines = [
        f"[bold yellow]📢 策略告警[/] {id_part}{action_markup} [bold]{alert.get('symbol')}[/]"
        f"{close_part}  [dim]{_fmt_dt(alert.get('dt'))}（K线 {_fmt_dt(alert.get('bar_dt'), 10)}）[/]",
    ]
    for i, detail in enumerate(details):
        branch = "└" if i == len(details) - 1 else "├"
        lines.append(f"   [dim]{branch}[/] {detail}")
    return "\n".join(lines)


def build_alert_options(
    n: int = 10,
    alerts_path: Path = ALERTS_PATH,
    enrichments_path: Optional[Path] = None,
) -> List[Tuple[str, str]]:
    """最近告警的选择项（供终端 /研判 选择对话框），新→旧排序。

    Args:
        n: 最多取最近多少条告警。
        alerts_path / enrichments_path: 告警与研判文件路径（测试可指向临时目录）。

    Returns:
        (alert_id, markup 单行) 列表；无 id 的旧记录跳过，同 id 只保留最新一条。
    """
    enrichments = load_enrichments(enrichments_path)
    options: dict = {}
    for alert in read_recent_alerts(n, alerts_path):  # 旧→新
        alert_id = alert.get("id") or ""
        if not alert_id:
            continue
        action = str(alert.get("action", "?"))
        action_markup = _ACTION_MARKUP.get(action, f"[bold]{action}[/]")
        enrichment = enrichments.get(alert_id)
        if enrichment:
            conclusion = str(enrichment.get("conclusion", "?"))
            color = _CONCLUSION_COLORS.get(conclusion, "white")
            status = f"[{color}]已研判·{conclusion}[/]"
        else:
            status = "[yellow]未研判[/]"
        snapshot = alert.get("snapshot") or {}
        last_close = snapshot.get("last_close")
        close_part = f" @{last_close}" if last_close is not None else ""
        options.pop(alert_id, None)  # 同 id 取最新（位置也随之更新）
        options[alert_id] = (
            f"[dim]#{alert_id}[/] {action_markup} [bold]{alert.get('symbol')}[/]{close_part}"
            f"  [dim]{_fmt_dt(alert.get('dt'), 16)}[/]  {status}"
        )
    items = list(options.items())
    items.reverse()  # 新→旧，最新的排最上
    return items


def build_enrich_prompt(alert: dict) -> str:
    """构造标准研判 prompt（/研判 选定告警后提交给 agent）。

    显式指示 MCP 工具链与落盘要求，比裸文本"研判 #id"对 agent 更确定。
    """
    alert_id = alert.get("id") or ""
    symbol = alert.get("symbol", "")
    action = alert.get("action", "")
    return (
        f"请研判策略告警 #{alert_id}：{symbol} {action}"
        f"（K线 {_fmt_dt(alert.get('bar_dt'), 10)}，理由：{alert.get('reason', '')}）。\n"
        f"1. 用 strategy_alerts_list 获取该告警完整上下文与研判流程说明；\n"
        f"2. 用 czsc_multi_level_analysis 复核 {symbol} 的多级别缠论结构"
        f"（注意富途码转 yfinance 码），关注返回中的 data_quality_issues；\n"
        f"3. 用 yfinance 工具核对近期行情是否支持 {action} 方向；\n"
        f'4. 得出结论后必须调用 strategy_alert_enrich（alert_id="{alert_id}"，'
        f"conclusion=支持/反对/观望，confidence=高/中/低，summary=关键论据）落盘，"
        f"最后用中文简述研判结果。"
    )


def _load_cron_job(name: str, jobs_path: Path) -> Optional[dict]:
    if not jobs_path.exists():
        return None
    try:
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for job in jobs if isinstance(jobs, list) else []:
        if job.get("name") == name:
            return job
    return None


def _last_history_entry(name: str, history_path: Path) -> Optional[dict]:
    if not history_path.exists():
        return None
    last = None
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("name") == name:
            last = entry
    return last


def build_startup_lines(
    recent_n: int = 5,
    config: Optional[dict] = None,
    alerts_path: Path = ALERTS_PATH,
    jobs_path: Path = CRON_JOBS_PATH,
    history_path: Path = CRON_HISTORY_PATH,
    enrichments_path: Optional[Path] = None,
) -> List[str]:
    """monitor 启动时的策略概况汇总 + 最近告警回放。"""
    config = config or load_config()
    cron_name = (config.get("cron") or {}).get("name", "decidra_strategy_scan")
    watchlist = config.get("watchlist", [])

    job = _load_cron_job(cron_name, jobs_path)
    if job is None:
        sched = "[yellow]未注册（python -m decidra.strategy.runner install-cron）[/]"
    else:
        state = "[green]启用[/]" if job.get("enabled", True) else "[red]停用[/]"
        sched = f"{state} [{job.get('schedule')}] 下次 {_fmt_dt(job.get('next_run'), 16)} UTC"

    pool = ", ".join(watchlist[:3]) + ("…" if len(watchlist) > 3 else "")
    lines = [
        f"[bold cyan]── 策略监控 ──[/] 股票池 {len(watchlist)} 只（{pool}） ｜ 调度 {sched}",
    ]

    hist = _last_history_entry(cron_name, history_path)
    if hist:
        status = str(hist.get("status", "?"))
        color = "green" if status == "success" else "red"
        lines.append(f"   上次扫描 {_fmt_dt(hist.get('started_at'))} [{color}]{status}[/]")

    recent = read_recent_alerts(recent_n, alerts_path)
    if recent:
        enrichments = load_enrichments(enrichments_path)
        lines.append(f"   最近告警 {len(recent)} 条：")
        lines.extend(
            format_alert(alert, enrichments.get(alert.get("id") or "")) for alert in recent
        )
    else:
        lines.append("   [dim]暂无历史告警[/]")
    return lines
