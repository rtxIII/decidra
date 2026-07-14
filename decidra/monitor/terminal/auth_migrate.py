"""Decidra AI 配置到 OpenHarness settings 的幂等迁移。

将 Decidra ``config.ini`` 的 ``[Analyzer]`` 段 AI 配置迁移到
``~/.decidra/openharness/settings.json``，使终端 agent 免二次配置即可复用现有
凭证。

字段映射（config.ini ``[Analyzer]`` → settings.json）：

- ``anthropicapikey`` → ``api_key``
- ``anthropicmodel`` → ``model``
- ``anthropicmaxtokens`` → ``max_tokens``

幂等策略：只补齐 settings.json 中缺失或为空的字段，绝不覆盖用户已填的非空值
（例如用户手动填写的 ``base_url`` 中转地址）。因此重复运行安全。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...utils.global_vars import get_config, get_logger

# 迁移目标：与 runtime_bridge 的 OPENHARNESS_CONFIG_DIR 一致（定义于 global_vars）。
from ...utils.global_vars import (
    DECIDRA_PATH as DECIDRA_HOME,
    PATH_OPENHARNESS as OPENHARNESS_CONFIG_DIR,
    PATH_OPENHARNESS_SETTINGS as SETTINGS_PATH,
)

# config.ini [Analyzer] 段的源字段名。
_SRC_API_KEY = "anthropicapikey"
_SRC_MODEL = "anthropicmodel"
_SRC_MAX_TOKENS = "anthropicmaxtokens"

# 默认 profile（Anthropic 兼容 API）。
_DEFAULT_PROFILE = "claude-api"


@dataclass(frozen=True)
class MigrationResult:
    """迁移结果。

    Attributes:
        changed: 是否写入了变更（幂等：无缺失字段时为 False）。
        filled: 本次补齐的字段名列表。
        settings_path: settings.json 路径。
        detail: 面向用户的说明。
    """

    changed: bool
    filled: list[str]
    settings_path: Path
    detail: str


def _load_analyzer_config() -> dict[str, str]:
    """读取 config.ini 的 ``[Analyzer]`` 段为字典（失败返回空字典）。"""
    try:
        config = get_config("Analyzer")
        return config if isinstance(config, dict) else {}
    except Exception:
        return {}


def _load_settings_file() -> dict[str, object]:
    """读取现有 settings.json（不存在或损坏时返回空字典）。"""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _is_blank(value: object) -> bool:
    """判断字段是否缺失或为空（空串/None/纯空白）。"""
    return value is None or (isinstance(value, str) and not value.strip())


def migrate_ai_config(*, dry_run: bool = False) -> MigrationResult:
    """将 config.ini 的 AI 配置幂等迁移到 openharness settings.json。

    只补齐 settings.json 中缺失或为空的字段，不覆盖已有非空值。

    Args:
        dry_run: 为 True 时只计算变更不落盘。

    Returns:
        ``MigrationResult``：``changed`` 表示是否需要/发生写入。
    """
    logger = get_logger("terminal.auth_migrate")
    analyzer = _load_analyzer_config()
    settings = _load_settings_file()

    # 源值
    src_api_key = str(analyzer.get(_SRC_API_KEY, "") or "").strip()
    src_model = str(analyzer.get(_SRC_MODEL, "") or "").strip()
    src_max_tokens = str(analyzer.get(_SRC_MAX_TOKENS, "") or "").strip()

    filled: list[str] = []
    updated = dict(settings)

    # active_profile / base_url 缺失时补默认；已有值不动。
    if _is_blank(updated.get("active_profile")):
        updated["active_profile"] = _DEFAULT_PROFILE
        filled.append("active_profile")

    if _is_blank(updated.get("api_key")) and src_api_key:
        updated["api_key"] = src_api_key
        filled.append("api_key")

    if _is_blank(updated.get("model")) and src_model:
        updated["model"] = src_model
        filled.append("model")

    if _is_blank(updated.get("max_tokens")) and src_max_tokens:
        try:
            updated["max_tokens"] = int(src_max_tokens)
            filled.append("max_tokens")
        except ValueError:
            logger.warning("anthropicmaxtokens 非整数，跳过: %r", src_max_tokens)

    if not filled:
        return MigrationResult(
            changed=False,
            filled=[],
            settings_path=SETTINGS_PATH,
            detail="settings.json 已就绪，无需迁移",
        )

    if not dry_run:
        OPENHARNESS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            SETTINGS_PATH.chmod(0o600)
        except OSError:
            pass
        logger.info("已迁移 AI 配置到 %s，补齐字段: %s", SETTINGS_PATH, ", ".join(filled))

    return MigrationResult(
        changed=True,
        filled=filled,
        settings_path=SETTINGS_PATH,
        detail=f"补齐字段: {', '.join(filled)}",
    )
