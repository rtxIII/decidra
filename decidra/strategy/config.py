"""策略模块配置：``~/.decidra/strategy/config.json`` 的加载与默认生成。"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from ..utils.global_vars import PATH_STRATEGY_CONFIG

logger = logging.getLogger(__name__)

STRATEGY_HOME: Path = PATH_STRATEGY_CONFIG
CONFIG_PATH: Path = STRATEGY_HOME / "config.json"
MIN_NEWS_RADAR_POLL_INTERVAL_SECONDS = 120
NEWS_RADAR_URL_SCHEMES = frozenset({"http", "https"})
SUPPORTED_NEWS_RADAR_API_FORMATS = frozenset({"openai", "openai_compat"})
NEWS_RADAR_CREDENTIAL_FIELDS = frozenset({"api_key"})

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
    "news_radar": {
        "enabled": False,
        "schedule": "*/3 * * * *",
        "poll_interval_seconds": 180,
        "sources": [
            "cls-telegraph",
            "wallstreetcn-quick",
            "jin10",
            "xueqiu-hotstock",
            "gelonghui",
        ],
        "base_url": "https://newsnow.we2.xyz",
        "llm_profile": "deepseeker",
    },
}


class NewsRadarProfileError(ValueError):
    """news radar LLM profile 无法安全使用。"""

    def __init__(self, code: str, profile_name: str):
        self.code = code
        self.profile_name = profile_name
        super().__init__(f"{code}: {profile_name}")


@dataclass(frozen=True)
class ResolvedNewsRadarProfile:
    """已物化且通过 MVP 能力校验的 radar LLM profile。"""

    name: str
    provider: str
    api_format: str
    model: str
    base_url: str | None
    auth_kind: str
    credential_source: str
    api_key: str = field(repr=False)


def _reject_credential_fields(config: Any, config_scope: str) -> None:
    if not isinstance(config, dict):
        return
    credential_fields = NEWS_RADAR_CREDENTIAL_FIELDS.intersection(config)
    if credential_fields:
        field_names = ", ".join(sorted(credential_fields))
        raise ValueError(f"{config_scope} 不得包含凭证字段: {field_names}")


def normalize_news_radar_config(config: Any) -> Dict[str, Any]:
    """合并并校验 news_radar 局部配置。"""
    if not isinstance(config, dict):
        raise ValueError("news_radar 必须是字典")
    _reject_credential_fields(config, "news_radar")

    normalized_config = copy.deepcopy(DEFAULT_CONFIG["news_radar"])
    normalized_config.update(config)

    if type(normalized_config["enabled"]) is not bool:
        raise ValueError("news_radar.enabled 必须是布尔值")

    schedule = normalized_config["schedule"]
    if not isinstance(schedule, str) or not schedule.strip():
        raise ValueError("news_radar.schedule 必须是非空字符串")
    normalized_config["schedule"] = schedule.strip()

    poll_interval_seconds = normalized_config["poll_interval_seconds"]
    if (
        type(poll_interval_seconds) is not int
        or poll_interval_seconds < MIN_NEWS_RADAR_POLL_INTERVAL_SECONDS
    ):
        raise ValueError(
            "news_radar.poll_interval_seconds 必须是大于等于 120 的整数"
        )

    sources = normalized_config["sources"]
    if not isinstance(sources, list) or not all(
        isinstance(source_id, str) and source_id.strip()
        for source_id in sources
    ):
        raise ValueError("news_radar.sources 的条目必须是非空字符串")
    normalized_config["sources"] = [source_id.strip() for source_id in sources]

    base_url = normalized_config["base_url"]
    parsed_base_url = urlparse(base_url) if isinstance(base_url, str) else None
    if (
        parsed_base_url is None
        or parsed_base_url.scheme not in NEWS_RADAR_URL_SCHEMES
        or not parsed_base_url.netloc
    ):
        raise ValueError("news_radar.base_url 必须是有效的 HTTP(S) URL")

    llm_profile = normalized_config["llm_profile"]
    if llm_profile is not None:
        if not isinstance(llm_profile, str) or not llm_profile.strip():
            raise ValueError("news_radar.llm_profile 必须是 null 或非空字符串")
        normalized_config["llm_profile"] = llm_profile.strip()

    return normalized_config


def _load_openharness_settings() -> Any:
    """在 Decidra 配置目录生效后加载 OpenHarness settings。"""
    from ..utils.global_vars import ensure_openharness_env

    ensure_openharness_env()
    from openharness.config import load_settings

    return load_settings()


def resolve_news_radar_profile(
    news_radar_config: Dict[str, Any],
    *,
    settings: Any | None = None,
) -> ResolvedNewsRadarProfile:
    """选择并校验 news radar 使用的 OpenHarness profile。"""
    openharness_settings = (
        _load_openharness_settings() if settings is None else settings
    )
    configured_profile_name = news_radar_config["llm_profile"]
    profile_name = (
        openharness_settings.active_profile
        if configured_profile_name is None
        else configured_profile_name
    )
    profile_name = (
        profile_name.strip() if isinstance(profile_name, str) else ""
    )
    profiles = openharness_settings.merged_profiles()
    if not profile_name or profile_name not in profiles:
        raise NewsRadarProfileError("unknown_llm_profile", profile_name)
    selected_profile = profiles[profile_name]
    selected_api_format = selected_profile.api_format.strip().lower()
    selected_auth_source = selected_profile.auth_source.strip()
    if (
        selected_api_format not in SUPPORTED_NEWS_RADAR_API_FORMATS
        or not selected_auth_source.endswith("_api_key")
    ):
        raise NewsRadarProfileError("unsupported_llm_profile", profile_name)

    selected_settings = copy.deepcopy(openharness_settings)
    if profile_name != openharness_settings.active_profile:
        selected_settings.api_key = ""
    selected_settings.active_profile = profile_name
    materialized_settings = selected_settings.materialize_active_profile()
    try:
        resolved_auth = materialized_settings.resolve_auth()
    except Exception:
        raise NewsRadarProfileError(
            "llm_profile_auth_unavailable",
            profile_name,
        ) from None

    api_format = materialized_settings.api_format.strip().lower()
    if api_format not in SUPPORTED_NEWS_RADAR_API_FORMATS:
        raise NewsRadarProfileError("unsupported_llm_profile", profile_name)
    if resolved_auth.auth_kind != "api_key":
        raise NewsRadarProfileError("unsupported_llm_profile", profile_name)

    return ResolvedNewsRadarProfile(
        name=profile_name,
        provider=materialized_settings.provider,
        api_format=api_format,
        model=materialized_settings.model,
        base_url=materialized_settings.base_url,
        auth_kind=resolved_auth.auth_kind,
        credential_source=resolved_auth.source,
        api_key=resolved_auth.value,
    )


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

    _reject_credential_fields(config, "策略配置")
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    merged["news_radar"] = normalize_news_radar_config(
        config.get("news_radar", {})
    )
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
    _reject_credential_fields(config, "策略配置")
    _reject_credential_fields(config.get("news_radar"), "news_radar")
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
