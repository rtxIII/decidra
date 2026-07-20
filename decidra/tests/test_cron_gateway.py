"""cron_gateway 薄网关的集成测试（无 mock，真实 openharness 调用）。

``OPENHARNESS_CONFIG_DIR`` 指向临时目录隔离 cron_jobs.json，不触碰
``~/.decidra/openharness`` 的真实数据。验证网关如实转发 openharness
cron 服务：表达式校验、job 增删改查往返、调度器只读探测、日志目录。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from decidra.tasks import cron_gateway

_JOB_NAME = "decidra_test_gateway_job"


class CronGatewayTestCase(unittest.TestCase):
    """网关对 openharness cron 服务的转发行为。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("OPENHARNESS_CONFIG_DIR")
        os.environ["OPENHARNESS_CONFIG_DIR"] = self._tmp.name
        # 强制网关对临时配置目录重新收拢（mkdir 生效目录）。
        cron_gateway._env_ready = False

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("OPENHARNESS_CONFIG_DIR", None)
        else:
            os.environ["OPENHARNESS_CONFIG_DIR"] = self._old_env
        cron_gateway._env_ready = False
        self._tmp.cleanup()

    def test_validate_cron_expression(self) -> None:
        self.assertTrue(cron_gateway.validate_cron_expression("*/5 * * * *"))
        self.assertFalse(cron_gateway.validate_cron_expression("not a cron"))

    def test_upsert_load_delete_roundtrip(self) -> None:
        job = {
            "name": _JOB_NAME,
            "schedule": "*/5 * * * *",
            "command": "echo hi",
            "enabled": True,
        }
        # 隔离目录初始不含该 job
        self.assertNotIn(
            _JOB_NAME,
            {j.get("name") for j in cron_gateway.load_cron_jobs()},
        )

        cron_gateway.upsert_cron_job(job)
        self.assertIn(
            _JOB_NAME,
            {j.get("name") for j in cron_gateway.load_cron_jobs()},
        )

        self.assertTrue(cron_gateway.delete_cron_job(_JOB_NAME))
        self.assertNotIn(
            _JOB_NAME,
            {j.get("name") for j in cron_gateway.load_cron_jobs()},
        )
        # 二次删除：已不存在 → False
        self.assertFalse(cron_gateway.delete_cron_job(_JOB_NAME))

    def test_is_scheduler_running_returns_bool(self) -> None:
        self.assertIsInstance(cron_gateway.is_scheduler_running(), bool)

    def test_get_logs_dir_returns_path(self) -> None:
        self.assertIsInstance(cron_gateway.get_logs_dir(), Path)


if __name__ == "__main__":
    unittest.main()
