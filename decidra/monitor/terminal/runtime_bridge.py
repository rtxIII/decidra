"""OpenHarness/ohmo 运行时桥接。

将 OpenHarness 引擎以进程内方式驱动，供 Decidra 终端控制台使用。封装
``build_runtime`` / ``start_runtime`` / ``handle_line`` / ``close_runtime`` 生命周期，
并处理 T1/T3 已定位的三处集成约束：

1. mcp 符号别名 shim（openharness 0.1.9 用旧符号 ``streamable_http_client``）。
2. 配置目录收拢到 ``~/.decidra/``（``OPENHARNESS_CONFIG_DIR`` 与 ohmo workspace）。
3. 第三方 Anthropic 兼容中转按 user-agent 做 WAF 拦截，须注入带 async UA 覆盖
   event_hook 的 ``AsyncAnthropic``（SDK ``default_headers`` 不替换 UA、同步 hook 会被
   吞成 ``APIConnectionError``）。

这些约束的实证见 ``doc/terminal-integration.md``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

# —— 配置目录收拢到 ~/.decidra/，必须在导入 openharness 之前设置 ——
# 路径统一定义于 utils.global_vars（仅依赖标准库+yaml，先于 openharness 导入安全）
from ...utils.global_vars import (
    DECIDRA_PATH as DECIDRA_HOME,
    PATH_OHMO_WORKSPACE as OHMO_WORKSPACE,
    PATH_OPENHARNESS as OPENHARNESS_CONFIG_DIR,
)

# 网关按 user-agent 拦截 SDK 默认 UA；覆盖为无害 UA 即可通过 WAF。
GATEWAY_USER_AGENT: str = "decidra-terminal/1.0"

_BOOTSTRAPPED: bool = False


def _bootstrap_openharness() -> None:
    """在导入 openharness 之前完成环境准备（幂等）。

    设置 ``OPENHARNESS_CONFIG_DIR`` 并为 mcp 注入旧符号别名。必须在任何
    ``openharness`` / ``ohmo`` 导入之前调用。
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    OPENHARNESS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPENHARNESS_CONFIG_DIR", str(OPENHARNESS_CONFIG_DIR))

    # mcp 别名 shim：openharness 0.1.9 硬 import 旧符号名 streamable_http_client。
    import mcp.client.streamable_http as _streamable_http

    if not hasattr(_streamable_http, "streamable_http_client"):
        _streamable_http.streamable_http_client = _streamable_http.streamablehttp_client

    _BOOTSTRAPPED = True


_bootstrap_openharness()

# 以下导入依赖 _bootstrap_openharness() 已执行。
import httpx  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from openharness.api.client import AnthropicApiClient  # noqa: E402
from openharness.api.client import SupportsStreamingMessages  # noqa: E402
from openharness.auth.manager import AuthManager  # noqa: E402
from openharness.config import load_settings  # noqa: E402
from openharness.ui.runtime import (  # noqa: E402
    RuntimeBundle,
    build_runtime,
    close_runtime,
    handle_line,
    start_runtime,
)

from ohmo.memory import create_memory_command_backend  # noqa: E402
from ohmo.prompts import build_ohmo_system_prompt  # noqa: E402
from ohmo.session_storage import OhmoSessionBackend  # noqa: E402
from ohmo.workspace import (  # noqa: E402
    get_memory_dir,
    get_skills_dir,
    initialize_workspace,
)

from ...utils.global_vars import get_logger  # noqa: E402

# 回调类型别名（与 openharness.ui.runtime 对齐）。
SystemPrinter = Callable[[str], Awaitable[None]]
StreamRenderer = Callable[[object], Awaitable[None]]
ClearHandler = Callable[[], Awaitable[None]]
PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]


async def _default_permission_prompt(tool_name: str, reason: str) -> bool:
    """保守默认权限回调：拒绝需确认的工具执行。

    T5 会以 Textual 对话框式回调替换本实现。在此之前，任何需要确认的工具
    一律拒绝，避免 agent 静默执行破坏性操作。

    Args:
        tool_name: 待执行的工具名。
        reason: 引擎给出的需确认原因。

    Returns:
        始终为 ``False``（拒绝）。
    """
    return False


async def _default_ask_user_prompt(question: str) -> str:
    """保守默认追问回调：返回空串。

    T5 会以 Textual 输入对话框替换本实现。

    Args:
        question: 引擎向用户提出的问题。

    Returns:
        空字符串。
    """
    return ""


def _build_api_client() -> SupportsStreamingMessages:
    """构造带 user-agent 覆盖的 Anthropic client。

    绕过第三方中转的 user-agent WAF 拦截。构造 openharness 的
    ``AnthropicApiClient`` 后，将其内部 ``_client`` 替换为带 async UA 覆盖
    event_hook 的 ``AsyncAnthropic``。本项目路径 ``claude_oauth=False``，
    ``_refresh_client_auth`` 会提前 return，不会覆盖此注入。

    Returns:
        已注入 UA 覆盖的流式消息客户端。
    """
    settings = load_settings().materialize_active_profile()

    async def _ua_override(request: httpx.Request) -> None:
        request.headers["user-agent"] = GATEWAY_USER_AGENT

    client = AnthropicApiClient(api_key=settings.api_key, base_url=settings.base_url)
    client._client = AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
        http_client=httpx.AsyncClient(event_hooks={"request": [_ua_override]}),
    )
    return client


@dataclass(frozen=True)
class AuthStatus:
    """凭证自校验结果。

    Attributes:
        ok: 是否已就绪可发起请求。
        profile: 当前生效的 provider profile 名。
        model: 当前生效的模型名。
        detail: 面向用户的说明（就绪时为 auth source，未就绪时为错误原因）。
    """

    ok: bool
    profile: str
    model: str
    detail: str


def check_auth() -> AuthStatus:
    """在构建运行时之前自校验凭证是否就绪（不发起网络请求）。

    通过 ``resolve_auth`` 判断当前 profile 能否取到凭证，避免 ``build_runtime``
    内部因认证失败抛 ``SystemExit`` 拖垮 TUI。判据基于动态解析的 active profile，
    不硬编码 profile 名。

    Returns:
        ``AuthStatus``：``ok`` 表示凭证就绪。
    """
    try:
        settings = load_settings()
        profile_name, _ = settings.resolve_profile()
        materialized = settings.materialize_active_profile()
        try:
            resolved = settings.resolve_auth()
        except Exception as exc:  # ValueError 或 subscription 相关错误
            return AuthStatus(
                ok=False,
                profile=profile_name,
                model=materialized.model,
                detail=str(exc).strip() or f"{type(exc).__name__}",
            )
        if not (resolved.value or "").strip():
            return AuthStatus(
                ok=False,
                profile=profile_name,
                model=materialized.model,
                detail="凭证为空，请在 ~/.decidra/openharness/settings.json 填入 api_key",
            )
        return AuthStatus(
            ok=True,
            profile=profile_name,
            model=materialized.model,
            detail=f"来源: {resolved.source}",
        )
    except Exception as exc:
        return AuthStatus(ok=False, profile="", model="", detail=f"配置加载失败: {exc}")


async def _noop_system(message: str) -> None:
    """默认 print_system 回调：丢弃系统消息。"""
    return None


async def _noop_clear() -> None:
    """默认 clear_output 回调：不做任何清屏。"""
    return None


class TerminalRuntime:
    """OpenHarness/ohmo 会话的进程内驱动器。

    封装一个常驻的 ``RuntimeBundle``，向 Textual 控制台暴露
    ``start`` / ``submit`` / ``close``，使其可在 Decidra 事件循环内逐轮驱动引擎。
    会话在多次 ``submit`` 之间保持常驻（对话历史、skills、memory 复用）。

    Attributes:
        cwd: agent 的工作目录。
        model: 模型覆盖；``None`` 时用 settings 中的模型。
        max_turns: 单轮最大回合数；``None`` 时不限制。
        workspace: ohmo workspace 根目录（含 skills / memory / sessions）。
        include_project_memory: 是否加载项目级 memory。
        permission_mode: 权限模式，保守默认 ``"default"``（仅在工具需确认时弹审批）。
        permission_prompt: 工具执行审批回调；``None`` 时用保守默认（拒绝）。
        ask_user_prompt: 追问回调；``None`` 时用保守默认（空串）。
    """

    def __init__(
        self,
        cwd: str | Path,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        workspace: str | Path = OHMO_WORKSPACE,
        include_project_memory: bool = False,
        permission_mode: str = "default",
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
    ) -> None:
        """初始化终端运行时（不构建引擎，构建在 ``start`` 中进行）。"""
        self.cwd: str = str(Path(cwd).resolve())
        self.model: str | None = model
        self.max_turns: int | None = max_turns
        self.workspace: Path = Path(workspace)
        self.include_project_memory: bool = include_project_memory
        self.permission_mode: str = permission_mode
        self.permission_prompt: PermissionPrompt = permission_prompt or _default_permission_prompt
        self.ask_user_prompt: AskUserPrompt = ask_user_prompt or _default_ask_user_prompt
        self.logger = get_logger("terminal.runtime_bridge")
        self._bundle: RuntimeBundle | None = None
        self.auth_status: AuthStatus | None = None

    @property
    def is_ready(self) -> bool:
        """引擎是否已构建并可接受输入。"""
        return self._bundle is not None

    @property
    def session_id(self) -> str:
        """当前会话 id；未启动时为空串。"""
        return self._bundle.session_id if self._bundle is not None else ""

    @property
    def active_model(self) -> str:
        """当前生效的模型名；未启动时回退到构造入参。"""
        if self._bundle is not None:
            return self._bundle.engine.model
        return self.model or ""

    @property
    def skills_dir(self) -> Path:
        """ohmo skills 目录。"""
        return get_skills_dir(self.workspace)

    @property
    def memory_dir(self) -> Path:
        """ohmo memory 目录。"""
        return get_memory_dir(self.workspace)

    async def start(self) -> None:
        """构建并启动运行时（幂等）。

        先自校验凭证：未就绪则进入未连接态并直接返回，不构建引擎。凭证就绪后
        构建 ``RuntimeBundle``（注入 UA 覆盖的 client、ohmo system prompt、skills、
        memory 后端与权限回调）并跑会话启动钩子。构建过程捕获 ``SystemExit``
        （openharness 认证失败会抛此 ``BaseException``）与其他异常，转为未连接态而
        非崩屏。重复调用为无操作。
        """
        if self._bundle is not None:
            return
        self.auth_status = check_auth()
        if not self.auth_status.ok:
            self.logger.warning("终端未连接（凭证未就绪）: %s", self.auth_status.detail)
            return
        workspace_root = initialize_workspace(self.workspace)
        try:
            bundle = await build_runtime(
                cwd=self.cwd,
                api_client=_build_api_client(),
                model=self.model,
                max_turns=self.max_turns,
                permission_mode=self.permission_mode,
                system_prompt=build_ohmo_system_prompt(self.cwd, workspace=workspace_root),
                session_backend=OhmoSessionBackend(workspace_root),
                extra_skill_dirs=(str(get_skills_dir(workspace_root)),),
                memory_backend=create_memory_command_backend(workspace_root),
                include_project_memory=self.include_project_memory,
                permission_prompt=self.permission_prompt,
                ask_user_prompt=self.ask_user_prompt,
            )
        except SystemExit as exc:
            # openharness 认证失败以 SystemExit（BaseException）抛出，普通 except 抓不到。
            self.auth_status = AuthStatus(
                ok=False,
                profile=self.auth_status.profile,
                model=self.auth_status.model,
                detail=f"引擎认证失败: {exc}",
            )
            self.logger.error("终端未连接（引擎认证失败）: %s", exc)
            return
        except Exception as exc:
            self.auth_status = AuthStatus(
                ok=False,
                profile=self.auth_status.profile,
                model=self.auth_status.model,
                detail=f"运行时构建失败: {exc}",
            )
            self.logger.error("终端未连接（运行时构建失败）: %s", exc)
            return
        await start_runtime(bundle)
        self._bundle = bundle
        self.logger.info(
            "终端运行时已启动: model=%s session=%s workspace=%s",
            bundle.engine.model,
            bundle.session_id,
            workspace_root,
        )

    async def submit(
        self,
        line: str,
        *,
        render_event: StreamRenderer,
        print_system: SystemPrinter | None = None,
        clear_output: ClearHandler | None = None,
    ) -> None:
        """提交一行输入并驱动一轮引擎，逐个事件回调渲染。

        未连接（凭证未就绪或运行时构建失败）时，经 ``print_system`` 报出原因并
        返回，不抛异常、不崩屏。

        Args:
            line: 用户输入或斜杠命令。
            render_event: 消费每个 ``StreamEvent`` 的 async 回调。
            print_system: 系统消息回调；``None`` 时丢弃。
            clear_output: 清屏回调；``None`` 时不清屏。
        """
        emit_system = print_system or _noop_system
        if self._bundle is None:
            detail = self.auth_status.detail if self.auth_status else "运行时尚未启动"
            await emit_system(f"未连接：{detail}")
            return
        await handle_line(
            self._bundle,
            line,
            print_system=emit_system,
            render_event=render_event,
            clear_output=clear_output or _noop_clear,
        )

    def list_slash_commands(self) -> list[tuple[str, str]]:
        """已注册斜杠命令的 (name, description) 列表（name 不含斜杠）。

        供终端面板做输入命令提示；未连接（运行时尚未启动/构建失败）时返回空。
        """
        if self._bundle is None:
            return []
        try:
            return [(c.name, c.description) for c in self._bundle.commands.list_commands()]
        except Exception as exc:
            self.logger.debug("获取斜杠命令列表失败: %s", exc)
            return []

    async def close(self) -> None:
        """关闭运行时并释放资源（幂等）。"""
        if self._bundle is None:
            return
        try:
            await close_runtime(self._bundle)
        finally:
            self._bundle = None
            self.logger.info("终端运行时已关闭")

