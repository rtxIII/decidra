"""策略模块配置：``~/.decidra/strategy/config.json`` 的加载与默认生成。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..utils.global_vars import PATH_STRATEGY_CONFIG

logger = logging.getLogger(__name__)

STRATEGY_HOME: Path = PATH_STRATEGY_CONFIG
CONFIG_PATH: Path = STRATEGY_HOME / "config.json"

# 默认配置。watchlist 为富途代码；cron 调度器随 monitor 启停，
# 表达式不限定交易时段——monitor 开着即轮询，盘外无新 K 线由去重抑制。
# 每个启用策略注册独立 cron job（decidra.tasks 注册表）：strategies[].schedule
# 可按策略覆盖扫描频率，缺省回退顶层 cron.schedule。
DEFAULT_CONFIG: Dict[str, Any] = {
    "watchlist": ["HK.00700"],
    "kline_days": 730,
    "strategies": [
        {"name": "czsc_resonance", "enabled": True, "params": {}},
    ],
    "cron": {"schedule": "*/5 * * * *"},
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


def clean_watchlist(items: Any) -> List[str]:
    """过滤 watchlist 中的非法条目（非字符串/空白串），UI 打标与写盘共用同一语义。"""
    if not isinstance(items, list):
        return []
    return [code for code in items if isinstance(code, str) and code.strip()]


def save_config(config: Dict[str, Any], path: Path = CONFIG_PATH) -> None:
    """原子写回策略配置。

    原子写只保护读者（cron 扫描进程并发读不会读到半写状态）；多写者场景
    需由调用方持锁（见 update_watchlist）。
    """
    # 函数内导入：保持模块导入期不依赖 openharness
    from openharness.utils.fs import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def update_watchlist(stock_code: str, add: bool, path: Path = CONFIG_PATH) -> List[str]:
    """将股票加入/移出 watchlist 并落盘（幂等）。

    直接读写盘上原始 JSON 而非 ``load_config`` 的默认合并视图，只改 watchlist
    一个键：用户文件保持稀疏（默认值继续随代码流动），文件损坏时拒绝写入并
    抛错（与 load_config 的"不覆盖损坏文件"约定一致）；读改写全程持文件锁，
    防止并发写者互相覆盖。

    Args:
        stock_code: 富途股票代码。
        add: ``True`` 加入，``False`` 移出。
        path: 配置文件路径。

    Returns:
        更新后的 watchlist。

    Raises:
        ValueError: 配置文件已存在但损坏/格式非字典（须先人工修复）。
    """
    assert stock_code and isinstance(stock_code, str), "stock_code 不能为空"
    from openharness.utils.file_lock import exclusive_file_lock

    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(path.with_suffix(path.suffix + ".lock")):
        if path.exists():
            try:
                raw_config = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(
                    f"策略配置文件损坏，拒绝写入（请先人工修复 {path}）: {exc}"
                ) from exc
            if not isinstance(raw_config, dict):
                raise ValueError(f"策略配置文件格式非字典，拒绝写入（{path}）")
            existing_watchlist = raw_config.get("watchlist", [])
            if not isinstance(existing_watchlist, list):
                raise ValueError(
                    f"watchlist 字段非列表（{type(existing_watchlist).__name__}），"
                    f"拒绝写入以免丢失数据（请先人工修复 {path}）"
                )
        else:
            raw_config = {}

        watchlist = clean_watchlist(raw_config.get("watchlist", []))
        if add:
            if stock_code not in watchlist:
                watchlist.append(stock_code)
        else:
            watchlist = [code for code in watchlist if code != stock_code]
        raw_config["watchlist"] = watchlist
        save_config(raw_config, path)
    return watchlist
