"""策略模块配置：``~/.decidra/strategy/config.json`` 的加载与默认生成。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from ..utils.global_vars import PATH_STRATEGY_CONFIG

logger = logging.getLogger(__name__)

STRATEGY_HOME: Path = PATH_STRATEGY_CONFIG
CONFIG_PATH: Path = STRATEGY_HOME / "config.json"

# 默认配置。watchlist 为富途代码；cron 调度器随 monitor 启停，
# 表达式不限定交易时段——monitor 开着即轮询，盘外无新 K 线由去重抑制。
DEFAULT_CONFIG: Dict[str, Any] = {
    "watchlist": ["HK.00700"],
    "kline_days": 730,
    "strategies": [
        {"name": "czsc_resonance", "enabled": True, "params": {}},
    ],
    "cron": {"name": "decidra_strategy_scan", "schedule": "*/15 * * * *"},
}


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    """加载策略配置；文件不存在时写入默认配置并返回。

    与默认配置浅合并，保证新增配置键在旧配置文件上可用；文件损坏或格式
    非字典时告警并回退默认配置（不覆盖损坏文件，便于人工排查）。
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dict(DEFAULT_CONFIG)

    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("策略配置文件损坏，回退默认配置（%s）: %s", path, exc)
        return dict(DEFAULT_CONFIG)
    if not isinstance(config, dict):
        logger.warning("策略配置文件格式非字典，回退默认配置（%s）", path)
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    return merged
