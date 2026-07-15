"""cron 任务注册表：声明式产出 Decidra 全部周期任务并同步到 openharness。

任务形态（方案 A+B）：
- 每个启用策略一个独立 job（``decidra_strategy_<策略名>``），schedule 取
  ``strategies[].schedule``，缺省回退顶层 ``cron.schedule``——策略间频率独立、
  故障隔离（一个策略崩溃不影响其他 job）。
- 未来非策略任务（数据预取、报表等）在 ``build_jobs`` 中追加即可。

所有权约定：``sync_jobs`` 只清理 ``decidra_strategy_`` 前缀 + 显式遗留名单
（旧单体 ``decidra_strategy_scan``）中不在注册表内的 job；其余 job（含用户
手工注册的其他 ``decidra_`` 前缀 job）不受影响。
"""

from __future__ import annotations

import re
import shlex
import sys
from typing import Any, Dict, List, Optional

from ..strategy.config import DEFAULT_CONFIG, load_config
from ..utils.global_vars import PATH_REPO_ROOT, ensure_openharness_env, get_logger

logger = get_logger("tasks_registry")

# decidra_ 前缀用于 list 展示归类；删除所有权仅限策略前缀 + 遗留名单
JOB_PREFIX = "decidra_"
STRATEGY_JOB_PREFIX = "decidra_strategy_"
LEGACY_JOB_NAMES = frozenset({"decidra_strategy_scan"})
# 策略与顶层 cron.schedule 均未配置时的兜底扫描频率（单一事实来源：strategy.config）
DEFAULT_STRATEGY_SCHEDULE: str = DEFAULT_CONFIG["cron"]["schedule"]
# 策略名进入 job 名与 shell 命令行，仅允许安全字符
_STRATEGY_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def strategy_job_name(strategy_name: str) -> str:
    """策略名 → cron job 名。"""
    return f"{STRATEGY_JOB_PREFIX}{strategy_name}"


def build_jobs(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """按配置产出全部应注册的 cron job（纯函数，不触碰注册表）。

    Args:
        config: 策略配置，缺省读 ~/.decidra/strategy/config.json。

    Returns:
        job dict 列表（openharness upsert_cron_job 入参格式）。
    """
    config = config or load_config()
    default_schedule = (config.get("cron") or {}).get(
        "schedule", DEFAULT_STRATEGY_SCHEDULE
    )

    jobs: List[Dict[str, Any]] = []
    for item in config.get("strategies", []):
        if not item.get("enabled", True):
            continue
        name = item.get("name")
        if not name:
            continue
        # 策略名进入 job 名与 shell 命令（调度器以 shell 字符串执行），整批拒绝非法名
        # fullmatch：match+$ 会放过尾随换行符（$ 匹配末尾 \n 之前）
        if not isinstance(name, str) or not _STRATEGY_NAME_RE.fullmatch(name):
            raise ValueError(
                f"非法策略名 {name!r}（仅允许字母/数字/._-，将用于 cron job 名与 shell 命令）"
            )
        schedule = item.get("schedule") or default_schedule
        jobs.append({
            "name": strategy_job_name(name),
            "schedule": schedule,
            "command": (
                f'"{sys.executable}" -m decidra.strategy.runner run '
                f'--strategy {shlex.quote(name)}'
            ),
            "cwd": str(PATH_REPO_ROOT),
            "enabled": True,
        })
    return jobs


def sync_jobs(config: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """将注册表同步到 openharness：先写入应有 job，再删除失效的策略前缀/遗留 job。

    Args:
        config: 策略配置，缺省读 ~/.decidra/strategy/config.json。

    Returns:
        {"installed": [job 名], "removed": [job 名]}。

    Raises:
        ValueError: 任一 job 的 cron 表达式非法（整批拒绝，不做半同步）。
    """
    ensure_openharness_env()
    from openharness.services.cron import (
        delete_cron_job,
        load_cron_jobs,
        upsert_cron_job,
        validate_cron_expression,
    )

    desired = build_jobs(config)
    for job in desired:
        if not validate_cron_expression(job["schedule"]):
            raise ValueError(
                f"非法 cron 表达式: {job['schedule']!r}（job {job['name']}，5 段格式，UTC 语义）"
            )

    desired_names = {job["name"] for job in desired}

    # 先写后删：中途失败的窗口从"无任何策略 job"缩为"多一个旧 job"
    for job in desired:
        upsert_cron_job(job)
        logger.info("注册 cron job: %s [%s]", job["name"], job["schedule"])

    stale = [
        str(j.get("name"))
        for j in load_cron_jobs()
        if (
            str(j.get("name", "")).startswith(STRATEGY_JOB_PREFIX)
            or j.get("name") in LEGACY_JOB_NAMES
        )
        and j.get("name") not in desired_names
    ]
    for name in stale:
        delete_cron_job(name)
        logger.info("移除失效 cron job: %s", name)

    return {"installed": sorted(desired_names), "removed": stale}
