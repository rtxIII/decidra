"""cron_daemon 托管启停的集成测试（无 mock，真实拉起调度器子进程）。

通过 ``OPENHARNESS_CONFIG_DIR`` 指向临时目录隔离 PID/历史文件，
不触碰 ``~/.decidra/openharness`` 的真实数据。
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from decidra.monitor.terminal import cron_daemon
from decidra.monitor.terminal.cron_daemon import (
    start_cron_scheduler,
    stop_cron_scheduler,
)

# 子进程需导入 openharness 后才写 PID 文件，冷启动留足余量。
_PID_WAIT_SECONDS = 20.0
_POLL_INTERVAL_SECONDS = 0.2


class CronDaemonTestCase(unittest.IsolatedAsyncioTestCase):
    """托管调度器的启动、幂等与回收行为。"""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("OPENHARNESS_CONFIG_DIR")
        os.environ["OPENHARNESS_CONFIG_DIR"] = self._tmp.name

    async def asyncTearDown(self) -> None:
        await stop_cron_scheduler()
        if self._old_env is None:
            os.environ.pop("OPENHARNESS_CONFIG_DIR", None)
        else:
            os.environ["OPENHARNESS_CONFIG_DIR"] = self._old_env
        self._tmp.cleanup()

    def _pid_path(self) -> Path:
        from openharness.services.cron_scheduler import get_pid_path

        return get_pid_path()

    async def test_start_creates_child_and_stop_reaps_it(self) -> None:
        self.assertTrue(start_cron_scheduler())
        process = cron_daemon.get_managed_process()
        self.assertIsNotNone(process)

        pid_path = self._pid_path()
        deadline = time.monotonic() + _PID_WAIT_SECONDS
        while time.monotonic() < deadline and not pid_path.exists():
            self.assertIsNone(process.poll(), "调度器子进程提前退出")
            time.sleep(_POLL_INTERVAL_SECONDS)
        self.assertTrue(pid_path.exists(), "调度器未在期限内写入 PID 文件")
        self.assertEqual(int(pid_path.read_text().strip()), process.pid)

        # 已托管运行时重复启动应跳过
        self.assertFalse(start_cron_scheduler())

        await stop_cron_scheduler()
        self.assertIsNotNone(process.poll(), "关闭后子进程应已退出")
        self.assertFalse(pid_path.exists(), "优雅退出应清除 PID 文件")
        self.assertIsNone(cron_daemon.get_managed_process())

    async def test_skip_when_external_scheduler_running(self) -> None:
        # 用测试进程自身 PID 伪造"外部调度器存活"状态
        pid_path = self._pid_path()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        try:
            self.assertFalse(start_cron_scheduler())
            self.assertIsNone(cron_daemon.get_managed_process())
        finally:
            pid_path.unlink(missing_ok=True)

    async def test_stop_without_start_is_noop(self) -> None:
        await stop_cron_scheduler()
        self.assertIsNone(cron_daemon.get_managed_process())


if __name__ == "__main__":
    unittest.main()
