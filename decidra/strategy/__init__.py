"""策略模块：cron 驱动的策略扫描 Runner 与告警管道。

调用链路：cron job → ``python -m decidra.strategy.runner run`` → ``run_scan()``
→ 各策略 ``evaluate()`` → 去重 → ``alerts.jsonl`` → monitor 终端面板播报。

与旧 ``decidra/strategies`` 包（无运行时、未接入）无关，本包为 czsc 策略体系。
"""

from .alerts import Alert
from .config import load_config

__all__ = ["Alert", "load_config"]
