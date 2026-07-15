"""Cron 调度器随 monitor 启停的托管模块。

以直接子进程（非 daemon 化）方式运行 openharness 的 ``run_scheduler_loop``，
生命周期绑定 monitor：正常退出时 SIGTERM 回收；检测到外部调度器（如手动
``oh cron start`` 拉起的脱管 daemon）在运行时跳过启动、退出时不干预。

不复用 ``start_daemon()``：其裸 ``os.fork()`` 后不 exec，在多线程的 monitor
进程（Textual/asyncio + futu 回调线程）内 fork 会复制锁与文件描述符状态，
存在死锁与 macOS ObjC runtime abort 风险。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from ...utils.global_vars import DECIDRA_PATH as DECIDRA_HOME, get_logger

# SIGTERM 后的优雅退出等待；须小于 cleanup_resources 的 3 秒总超时。
STOP_GRACE_SECONDS: float = 2.0

# 子进程引导：等价于 cron_scheduler._run_daemon()，仅用公开符号拼写，
# 避免依赖私有函数名。
_CHILD_BOOTSTRAP: str = "\n".join(
    (
        "import asyncio, logging",
        "from openharness.config.paths import get_logs_dir",
        "from openharness.services.cron_scheduler import run_scheduler_loop",
        "logging.basicConfig(",
        "    filename=str(get_logs_dir() / 'cron_scheduler.log'),",
        "    level=logging.INFO,",
        "    format='%(asctime)s %(levelname)s %(message)s',",
        ")",
        "asyncio.run(run_scheduler_loop())",
    )
)

logger = get_logger(__name__)

_managed_process: subprocess.Popen | None = None


def get_managed_process() -> subprocess.Popen | None:
    """返回当前托管的调度器子进程（未托管时为 None）。"""
    return _managed_process


def start_cron_scheduler() -> bool:
    """启动托管的 cron 调度器子进程（幂等）。

    Returns:
        True 表示本次拉起了新调度器；False 表示已有调度器在运行
        （托管中或外部启动）或拉起失败，原因见日志。
    """
    global _managed_process

    if _managed_process is not None and _managed_process.poll() is None:
        logger.info("cron 调度器已由 monitor 托管运行 (pid=%d)", _managed_process.pid)
        return False

    # 与 runtime_bridge 一致：openharness 导入前收拢配置目录（幂等）。
    from ...utils.global_vars import ensure_openharness_env
    ensure_openharness_env()
    from openharness.config.paths import get_logs_dir
    from openharness.services.cron_scheduler import is_scheduler_running

    if is_scheduler_running():
        logger.info("检测到外部 cron 调度器已在运行，跳过托管启动")
        return False

    boot_log_path = get_logs_dir() / "cron_scheduler_boot.log"
    try:
        with boot_log_path.open("ab") as boot_log:
            _managed_process = subprocess.Popen(
                [sys.executable, "-c", _CHILD_BOOTSTRAP],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=boot_log,
            )
    except OSError as exc:
        logger.error("启动 cron 调度器失败: %s", exc)
        _managed_process = None
        return False

    logger.info("cron 调度器已随 monitor 启动 (pid=%d)", _managed_process.pid)
    return True


async def stop_cron_scheduler() -> None:
    """关闭托管的 cron 调度器（幂等，仅回收自己拉起的进程）。"""
    global _managed_process

    process = _managed_process
    _managed_process = None
    if process is None:
        return
    if process.poll() is not None:
        logger.info("cron 调度器已自行退出 (rc=%s)", process.returncode)
        return

    process.terminate()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(process.wait), timeout=STOP_GRACE_SECONDS
        )
        logger.info("cron 调度器已随 monitor 关闭")
    except asyncio.TimeoutError:
        process.kill()
        await asyncio.to_thread(process.wait)
        logger.warning("cron 调度器优雅退出超时，已强制结束")
