"""openharness cron 服务的薄网关——Decidra 侧对 openharness cron 的唯一接触面。

将原先散落在 ``tasks/registry.py``、``tasks/__main__.py``、
``monitor/terminal/cron_daemon.py`` 的 openharness 直连收拢到此处：

- job 增删改查：``openharness.services.cron``
- 调度器只读探测：``openharness.services.cron_scheduler.is_scheduler_running``
- 日志目录：``openharness.config.paths.get_logs_dir``

openharness 若发生签名漂移，改动范围收敛到本文件。openharness 为延迟导入
（模块 import 期不依赖），并在首次调用前统一收拢配置目录。

例外：``run_scheduler_loop`` 在 ``cron_daemon`` 的裸子进程 bootstrap 源码串中
执行，须以 openharness 全限定名直连，不经本网关。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..utils.global_vars import ensure_openharness_env

# openharness 配置目录仅需收拢一次（ensure_openharness_env 本身幂等，此处避免
# 在 validate 等循环调用点重复 setdefault/mkdir）。
_env_ready: bool = False


def _ensure_env() -> None:
    """在任何 openharness 导入/调用前收拢配置目录（进程内仅生效一次）。"""
    global _env_ready
    if not _env_ready:
        ensure_openharness_env()
        _env_ready = True


def load_cron_jobs() -> List[Dict[str, Any]]:
    """返回 openharness 已注册的全部 cron job。"""
    _ensure_env()
    from openharness.services.cron import load_cron_jobs as _impl

    return _impl()


def upsert_cron_job(job: Dict[str, Any]) -> None:
    """新增或更新一个 cron job（按 ``name`` 幂等）。"""
    _ensure_env()
    from openharness.services.cron import upsert_cron_job as _impl

    _impl(job)


def delete_cron_job(name: str) -> bool:
    """按名删除 cron job；返回是否删除了一个已存在的 job。"""
    _ensure_env()
    from openharness.services.cron import delete_cron_job as _impl

    return _impl(name)


def validate_cron_expression(expression: str) -> bool:
    """校验 5 段 cron 表达式是否合法（UTC 语义）。"""
    _ensure_env()
    from openharness.services.cron import validate_cron_expression as _impl

    return _impl(expression)


def is_scheduler_running() -> bool:
    """探测是否已有 cron 调度器在运行（monitor 托管或外部 ``oh cron start``）。"""
    _ensure_env()
    from openharness.services.cron_scheduler import is_scheduler_running as _impl

    return _impl()


def get_logs_dir() -> Path:
    """openharness 日志目录（cron 调度器日志落此）。"""
    _ensure_env()
    from openharness.config.paths import get_logs_dir as _impl

    return _impl()
