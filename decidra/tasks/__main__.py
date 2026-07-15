"""``python -m decidra.tasks`` 命令行入口。"""

from __future__ import annotations

import argparse
import json

from ..utils.global_vars import ensure_openharness_env
from .registry import JOB_PREFIX, sync_jobs


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Decidra cron 任务注册表")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install", help="按注册表同步全部 cron job（含清理失效 job）")
    sub.add_parser("list", help="查看已注册的 decidra 任务")
    args = parser.parse_args(argv)

    if args.command == "install":
        result = sync_jobs()
        for name in result["installed"]:
            print(f"已注册: {name}")
        for name in result["removed"]:
            print(f"已移除: {name}")
    else:
        ensure_openharness_env()
        from openharness.services.cron import load_cron_jobs

        jobs = [
            j for j in load_cron_jobs()
            if str(j.get("name", "")).startswith(JOB_PREFIX)
        ]
        print(json.dumps(jobs, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
