"""策略信息的终端展示：Rich markup 文本，供 monitor 终端面板播报。

告警块、启动概况与新闻雷达都是纯函数产出字符串，不依赖 Textual，便于单测。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from rich.markup import escape

from ..utils.global_vars import PATH_DATA, PATH_OPENHARNESS_DATA
from .alerts import ALERTS_PATH, load_enrichments, read_recent_alerts
from .config import load_config

# 与 runtime_bridge / cron_daemon 一致的 openharness 数据目录（定义于 global_vars）
OPENHARNESS_DATA_DIR: Path = PATH_OPENHARNESS_DATA
CRON_JOBS_PATH: Path = OPENHARNESS_DATA_DIR / "cron_jobs.json"
CRON_HISTORY_PATH: Path = OPENHARNESS_DATA_DIR / "cron_history.jsonl"
# monitor 维护的股票基础信息缓存（与 monitor/main/data.py 的 BASICINFO_CACHE_FILE 同一文件）
BASICINFO_CACHE_PATH: Path = PATH_DATA / "stock_basicinfo_cache.json"

_ACTION_MARKUP = {
    "BUY": "[bold green]▲ BUY[/]",
    "SELL": "[bold red]▼ SELL[/]",
}

# _stock_name 的进程内缓存：((路径, 文件 mtime), code → name)
_names_cache: Tuple[Optional[tuple], dict] = (None, {})


def _stock_name(code: str, cache_path: Optional[Path] = None) -> str:
    """从 monitor 的 basicinfo 缓存查股票名称，查不到返回空串。

    按（路径, mtime）做进程内缓存，避免每条告警重读整个缓存文件；文件
    不存在或损坏时静默退化（告警只显示代码）。cache_path 缺省用模块级
    BASICINFO_CACHE_PATH（测试可改指临时文件）。
    """
    global _names_cache
    cache_path = cache_path or BASICINFO_CACHE_PATH
    try:
        cache_key = (str(cache_path), cache_path.stat().st_mtime)
    except OSError:
        return ""
    if _names_cache[0] != cache_key:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = data.get("data", {}) if isinstance(data, dict) else {}
            names = {
                c: str(info.get("name", ""))
                for c, info in entries.items() if isinstance(info, dict)
            }
        except (json.JSONDecodeError, OSError):
            names = {}
        _names_cache = (cache_key, names)
    return _names_cache[1].get(code, "")


def _symbol_display(symbol) -> str:
    """代码 + 名称（如"HK.00700 腾讯控股"），名称查不到时只显代码。"""
    code = str(symbol or "")
    name = _stock_name(code)
    return f"{code} {name}" if name else code


def _fmt_dt(value, length: int = 19) -> str:
    return str(value or "")[:length].replace("T", " ")


_CONCLUSION_COLORS = {"支持": "green", "反对": "red", "观望": "yellow"}

_NEWS_RADAR_STARTUP_EVENT_LIMIT = 5
_NEWS_RADAR_ATTENTION_MARKUP = {
    "high": "[bold red]高关注[/]",
    "medium": "[yellow]中关注[/]",
    "low": "[dim]低关注[/]",
}
_NEWS_RADAR_RELATION_LABELS = {
    "direct": "直接相关",
    "sector": "行业关联",
    "macro": "宏观关联",
    "hotspot": "热点关联",
}
_NEWS_RADAR_SENTIMENT_LABELS = {
    "positive": "正面",
    "negative": "负面",
    "neutral": "中性",
    "uncertain": "不确定",
}
_NEWS_RADAR_CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}
_NEWS_RADAR_URL_SCHEMES = frozenset({"http", "https"})
_NEWS_RADAR_DISCLAIMER = "新闻关注提示，不构成股票池调整或交易建议"


def _escape_news_radar_text(value) -> str:
    normalized_text = " ".join(str(value or "").split())
    return escape(normalized_text)


def _format_news_radar_url(value) -> str:
    raw_url = str(value or "").strip()
    if not raw_url or any(character.isspace() for character in raw_url):
        return "[dim]原文链接不可用[/]"
    parsed_url = urlparse(raw_url)
    if (
        parsed_url.scheme.lower() not in _NEWS_RADAR_URL_SCHEMES
        or not parsed_url.netloc
    ):
        return "[dim]原文链接不可用[/]"
    return _escape_news_radar_text(raw_url)


def _format_news_radar_stocks(value) -> str:
    if not isinstance(value, list):
        return "无已知关联标的"
    stock_labels = []
    for stock in value:
        if not isinstance(stock, dict):
            continue
        stock_code = _escape_news_radar_text(stock.get("code"))
        stock_name = _escape_news_radar_text(stock.get("name"))
        if stock_code and stock_name:
            stock_labels.append(f"{stock_code} {stock_name}")
        elif stock_code or stock_name:
            stock_labels.append(stock_code or stock_name)
    return "、".join(stock_labels) or "无已知关联标的"


def _format_news_radar_event(event: dict, event_number: int) -> List[str]:
    attention = _NEWS_RADAR_ATTENTION_MARKUP.get(
        str(event.get("attention") or ""),
        "[dim]未知关注等级[/]",
    )
    title = _escape_news_radar_text(event.get("title")) or "未命名事件"
    relation_type = str(event.get("relation_type") or "")
    relation_label = _escape_news_radar_text(
        _NEWS_RADAR_RELATION_LABELS.get(
            relation_type,
            relation_type or "未知关联",
        )
    )
    sentiment = str(event.get("sentiment") or "")
    sentiment_label = _escape_news_radar_text(
        _NEWS_RADAR_SENTIMENT_LABELS.get(
            sentiment,
            sentiment or "未知",
        )
    )
    confidence = str(event.get("confidence") or "")
    confidence_label = _escape_news_radar_text(
        _NEWS_RADAR_CONFIDENCE_LABELS.get(
            confidence,
            confidence or "未知",
        )
    )
    related_stocks = _format_news_radar_stocks(
        event.get("related_stocks")
    )
    reason = _escape_news_radar_text(event.get("reason")) or "未提供关注原因"
    source_id = _escape_news_radar_text(event.get("source_id")) or "未知源"
    effective_time = _escape_news_radar_text(
        str(event.get("effective_time") or "").replace("T", " ")
    ) or "未知时间"
    time_label = (
        "发布时间"
        if event.get("time_source") == "pubDate"
        else "来源更新时间"
    )
    source_url = _format_news_radar_url(event.get("url"))
    return [
        (
            f"   {event_number}. {attention} [bold]{title}[/] ｜ "
            f"{relation_label} ｜ 关联 {related_stocks} ｜ "
            f"情绪 {sentiment_label} ｜ 置信度 {confidence_label}"
        ),
        (
            f"      {reason} ｜ 来源 {source_id} ｜ "
            f"{time_label} {effective_time} ｜ 原文 {source_url}"
        ),
    ]


def _format_news_radar_error(error: dict) -> str:
    error_code = _escape_news_radar_text(error.get("code")) or "unknown_error"
    source_id = _escape_news_radar_text(error.get("source_id"))
    detail = _escape_news_radar_text(error.get("detail"))
    error_parts = []
    if source_id:
        error_parts.append(f"数据源 {source_id}")
    error_parts.append(error_code)
    if detail:
        error_parts.append(detail)
    return f"   [yellow]⚠ 系统提示[/] {' ｜ '.join(error_parts)}"


def format_news_radar_record(record: dict) -> str:
    """将一条 news_radar JSONL 记录格式化为安全的 Rich markup 区块。"""
    is_startup = record.get("mode") == "startup"
    mode_label = (
        "当前快照，不代表完整离线历史"
        if is_startup
        else "实时更新"
    )
    lines = [
        f"[bold cyan]📡 实时新闻关注雷达[/] [dim]{mode_label}[/]"
    ]

    events = record.get("events")
    if not isinstance(events, list):
        events = []
    displayed_events = (
        events[:_NEWS_RADAR_STARTUP_EVENT_LIMIT]
        if is_startup
        else events
    )
    for event_number, event in enumerate(displayed_events, start=1):
        if isinstance(event, dict):
            lines.extend(_format_news_radar_event(event, event_number))

    errors = record.get("errors")
    if isinstance(errors, list):
        lines.extend(
            _format_news_radar_error(error)
            for error in errors
            if isinstance(error, dict)
        )
    lines.append(f"[dim]{_NEWS_RADAR_DISCLAIMER}[/]")
    return "\n".join(lines)


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
    ]
    caveats = alert.get("caveats") or []
    details.extend(f"[bold red]⚠ {caveat}[/]" for caveat in caveats)
    details.append(
        f"周线 {weekly} ｜ 共振 {cross} ｜ 日线买卖点 {daily_part}"
        f" ｜ 策略 [dim]{alert.get('strategy', '')}[/]"
    )
    if enrichment:
        conclusion = str(enrichment.get("conclusion", "?"))
        color = _CONCLUSION_COLORS.get(conclusion, "white")
        details.append(
            f"研判: [{color}]{conclusion}[/]（置信度 {enrichment.get('confidence', '中')}）"
            f" {enrichment.get('summary', '')}"
        )

    lines = [
        f"[bold yellow]📢 策略告警[/] {id_part}{action_markup} [bold]{_symbol_display(alert.get('symbol'))}[/]"
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
            f"[dim]#{alert_id}[/] {action_markup} [bold]{_symbol_display(alert.get('symbol'))}[/]{close_part}"
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


def _fmt_rate(result: Optional[dict]) -> str:
    """命中率结果 → "62%(n=21)"；rate 为 null（样本不足）显示 "—(n=k)"。"""
    if not isinstance(result, dict):
        return "—"
    rate = result.get("rate")
    n = result.get("n", 0)
    body = f"{rate * 100:.0f}%" if isinstance(rate, (int, float)) else "—"
    return f"{body}(n={n})"


def _fmt_avg(result: Optional[dict]) -> str:
    """平均前向收益结果 → "+1.2%(n=8)"；样本不足显示 "—(n=k)"。"""
    if not isinstance(result, dict):
        return "—"
    avg = result.get("avg")
    n = result.get("n", 0)
    body = f"{avg * 100:+.1f}%" if isinstance(avg, (int, float)) else "—"
    return f"{body}(n={n})"


def format_evals_summary_lines(report: dict) -> List[str]:
    """评测报告 → 启动概况的两行摘要（Rich markup）。"""
    window = report.get("window_days", "?")
    horizon = report.get("horizon_days", "?")
    avg = report.get("avg_forward_return") or {}
    calibration = report.get("confidence_calibration") or {}
    return [
        (
            f"   [bold cyan]📊 评测[/]（近 {window} 日, T+{horizon}）: "
            f"信号命中 {_fmt_rate(report.get('signal_hit_rate'))} ｜ "
            f"前向收益 BUY {_fmt_avg(avg.get('BUY'))} / SELL {_fmt_avg(avg.get('SELL'))}"
        ),
        (
            f"      [dim]AI 支持命中[/] {_fmt_rate(report.get('enriched_hit_rate'))} ｜ "
            f"[dim]反对规避[/] {_fmt_rate(report.get('veto_avoid_rate'))} ｜ "
            f"[dim]校准[/] 高 {_fmt_rate(calibration.get('高'))} / "
            f"中 {_fmt_rate(calibration.get('中'))} / 低 {_fmt_rate(calibration.get('低'))}"
        ),
    ]


def _load_cron_jobs_by_name(jobs_path: Path) -> dict:
    """一次读入 cron 注册表，name → job（供多策略循环查询，避免逐策略重读文件）。"""
    if not jobs_path.exists():
        return {}
    try:
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(jobs, list):
        return {}
    return {job.get("name"): job for job in jobs if isinstance(job, dict)}


def _last_history_entries(names, history_path: Path) -> dict:
    """单趟扫描执行历史，取每个目标 job 的最后一条记录（history 无轮转，只扫一遍）。"""
    if not history_path.exists():
        return {}
    wanted = set(names)
    last: dict = {}
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("name") in wanted:
            last[entry["name"]] = entry
    return last


def build_startup_lines(
    recent_n: int = 5,
    config: Optional[dict] = None,
    alerts_path: Path = ALERTS_PATH,
    jobs_path: Path = CRON_JOBS_PATH,
    history_path: Path = CRON_HISTORY_PATH,
    enrichments_path: Optional[Path] = None,
) -> List[str]:
    """monitor 启动时的策略概况汇总 + 最近告警回放。

    每个启用策略对应一个独立 cron job（decidra.tasks 注册表），逐个汇报
    调度状态与上次扫描结果。
    """
    config = config or load_config()
    watchlist = config.get("watchlist", [])
    enabled = [
        s.get("name") for s in config.get("strategies", [])
        if s.get("enabled", True) and s.get("name")
    ]

    pool = ", ".join(watchlist[:3]) + ("…" if len(watchlist) > 3 else "")
    lines = [
        f"[bold cyan]── 策略监控 ──[/] 股票池 {len(watchlist)} 只（{pool}） ｜ 启用策略 {len(enabled)} 个",
    ]

    # 延迟导入避免 display（可能被面板加载）在导入期拉起 tasks 包
    from ..tasks.registry import strategy_job_name

    job_names = {strategy: strategy_job_name(strategy) for strategy in enabled}
    jobs_by_name = _load_cron_jobs_by_name(jobs_path)
    history_by_name = _last_history_entries(job_names.values(), history_path)

    for strategy, job_name in job_names.items():
        job = jobs_by_name.get(job_name)
        if job is None:
            sched = "[yellow]未注册（python -m decidra.tasks install）[/]"
        else:
            state = "[green]启用[/]" if job.get("enabled", True) else "[red]停用[/]"
            sched = f"{state} [{job.get('schedule')}] 下次 {_fmt_dt(job.get('next_run'), 16)} UTC"
        line = f"   {strategy}: {sched}"
        hist = history_by_name.get(job_name)
        if hist:
            status = str(hist.get("status", "?"))
            color = "green" if status == "success" else "red"
            line += f" ｜ 上次 {_fmt_dt(hist.get('started_at'))} [{color}]{status}[/]"
        lines.append(line)

    # 评测摘要（懒加载，只读 outcomes/enrichments，失败不阻塞启动概况）
    if (config.get("evals") or {}).get("enabled", True):
        try:
            from .evals import report as evals_report

            lines.extend(format_evals_summary_lines(evals_report(config=config)))
        except Exception:  # noqa: BLE001 - 概况非关键路径，任何异常降级为不展示
            pass

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
