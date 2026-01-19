"""
Claude AI Client - 基于Anthropic SDK的AI分析客户端

提供股票分析、投资建议、对话交互等AI功能
支持完整的 tool use 能力，可动态调用股票数据API

依赖: anthropic SDK
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
from ...base.order import OrderType
from ...base.trading import TradingAdvice, TradingOrder
from ...base.ai import AIRequest, AIAnalysisRequest, AITradingAdviceRequest, AIAnalysisResponse
from ...utils.global_vars import get_logger, get_config

# Anthropic SDK (支持完整 tool use)
try:
    import anthropic
    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    get_logger(__name__).warning("anthropic SDK not found, please install anthropic SDK to use this feature")
    ANTHROPIC_SDK_AVAILABLE = False
    anthropic = None

# claude-code-sdk / claude-agent-sdk 作为备选（支持 tool use）
try:
    # 优先尝试新版 claude-agent-sdk
    from claude_agent_sdk import query as agent_query, ClaudeAgentOptions, tool as agent_tool, create_sdk_mcp_server
    from claude_agent_sdk.types import SystemMessage, AssistantMessage, ResultMessage
    CLAUDE_CODE_SDK_AVAILABLE = True
    query = agent_query
    ClaudeCodeOptions = ClaudeAgentOptions
    CLAUDE_AGENT_SDK_TOOL_SUPPORT = True
except ImportError:
    try:
        # 回退到旧版 claude-code-sdk
        from claude_code_sdk import query, ClaudeCodeOptions
        from claude_code_sdk.types import SystemMessage, AssistantMessage, ResultMessage
        CLAUDE_CODE_SDK_AVAILABLE = True
        CLAUDE_AGENT_SDK_TOOL_SUPPORT = False
        agent_tool = None
        create_sdk_mcp_server = None
    except ImportError:
        CLAUDE_CODE_SDK_AVAILABLE = False
        CLAUDE_AGENT_SDK_TOOL_SUPPORT = False
        query = None
        ClaudeCodeOptions = None
        SystemMessage = None
        AssistantMessage = None
        ResultMessage = None
        agent_tool = None
        create_sdk_mcp_server = None


# ================== 股票数据工具定义 ==================

STOCK_DATA_TOOLS = [
    {
        "name": "get_realtime_quote",
        "description": "获取股票实时行情报价，包括当前价格、涨跌幅、成交量、换手率等数据",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，格式如 ['HK.00700', 'US.AAPL']"
                }
            },
            "required": ["stock_codes"]
        }
    },
    {
        "name": "get_stock_kline",
        "description": "获取股票K线数据，用于技术分析。支持日K、周K、月K等多种周期",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，格式如 'HK.00700'"
                },
                "ktype": {
                    "type": "string",
                    "enum": ["K_DAY", "K_WEEK", "K_MON", "K_1M", "K_5M", "K_15M", "K_30M", "K_60M"],
                    "description": "K线类型：K_DAY=日K, K_WEEK=周K, K_MON=月K, K_1M=1分钟K等",
                    "default": "K_DAY"
                },
                "num": {
                    "type": "integer",
                    "description": "获取K线数量，默认100根",
                    "default": 100
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_capital_flow",
        "description": "获取股票资金流向数据，包括主力资金、超大单、大单、中单、小单的净流入流出情况",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，格式如 'HK.00700'"
                },
                "period_type": {
                    "type": "string",
                    "enum": ["INTRADAY", "DAY", "WEEK", "MONTH"],
                    "description": "资金流向周期：INTRADAY=日内, DAY=日, WEEK=周, MONTH=月",
                    "default": "INTRADAY"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_orderbook",
        "description": "获取股票五档买卖盘数据，显示当前买卖挂单的价格和数量分布",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，格式如 'HK.00700'"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_stock_basicinfo",
        "description": "获取股票基本信息，包括公司名称、行业、市值等基本面数据",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，格式如 'HK.00700'"
                }
            },
            "required": ["stock_code"]
        }
    }
]


# ================== Claude Agent SDK MCP 工具创建器 ==================

class StockDataMCPServerBuilder:
    """
    股票数据 MCP 服务器构建器
    用于 Claude Agent SDK 的 tool use 功能
    """

    def __init__(self, tool_executor: 'StockDataToolExecutor'):
        """
        初始化 MCP 服务器构建器

        Args:
            tool_executor: StockDataToolExecutor 实例
        """
        self.tool_executor = tool_executor
        self.logger = get_logger(__name__)

    def create_mcp_server(self):
        """
        创建包含股票数据工具的 MCP 服务器

        Returns:
            MCP 服务器实例，如果不支持则返回 None
        """
        if not CLAUDE_AGENT_SDK_TOOL_SUPPORT or not create_sdk_mcp_server or not agent_tool:
            self.logger.warning("Claude Agent SDK tool support 不可用")
            return None

        try:
            # 创建工具函数引用
            executor = self.tool_executor

            # 定义 MCP 工具
            @agent_tool(
                "get_realtime_quote",
                "获取股票实时行情报价，包括当前价格、涨跌幅、成交量、换手率等数据",
                {"stock_codes": list}
            )
            async def get_realtime_quote_tool(args: dict) -> dict:
                result = executor.execute_tool("get_realtime_quote", args)
                return {"content": [{"type": "text", "text": result}]}

            @agent_tool(
                "get_stock_kline",
                "获取股票K线数据，用于技术分析。支持日K、周K、月K等多种周期",
                {"stock_code": str, "ktype": str, "num": int}
            )
            async def get_stock_kline_tool(args: dict) -> dict:
                result = executor.execute_tool("get_stock_kline", args)
                return {"content": [{"type": "text", "text": result}]}

            @agent_tool(
                "get_capital_flow",
                "获取股票资金流向数据，包括主力资金、超大单、大单、中单、小单的净流入流出情况",
                {"stock_code": str, "period_type": str}
            )
            async def get_capital_flow_tool(args: dict) -> dict:
                result = executor.execute_tool("get_capital_flow", args)
                return {"content": [{"type": "text", "text": result}]}

            @agent_tool(
                "get_orderbook",
                "获取股票五档买卖盘数据，显示当前买卖挂单的价格和数量分布",
                {"stock_code": str}
            )
            async def get_orderbook_tool(args: dict) -> dict:
                result = executor.execute_tool("get_orderbook", args)
                return {"content": [{"type": "text", "text": result}]}

            @agent_tool(
                "get_stock_basicinfo",
                "获取股票基本信息，包括公司名称、行业、市值等基本面数据",
                {"stock_code": str}
            )
            async def get_stock_basicinfo_tool(args: dict) -> dict:
                result = executor.execute_tool("get_stock_basicinfo", args)
                return {"content": [{"type": "text", "text": result}]}

            # 创建 MCP 服务器
            mcp_server = create_sdk_mcp_server(
                name="stock-data-tools",
                version="1.0.0",
                tools=[
                    get_realtime_quote_tool,
                    get_stock_kline_tool,
                    get_capital_flow_tool,
                    get_orderbook_tool,
                    get_stock_basicinfo_tool
                ]
            )

            self.logger.info("股票数据 MCP 服务器创建成功")
            return mcp_server

        except Exception as e:
            self.logger.error(f"创建 MCP 服务器失败: {e}")
            return None

    @staticmethod
    def get_allowed_tools() -> list:
        """获取允许使用的工具列表（MCP 格式）"""
        return [
            "mcp__stock-data-tools__get_realtime_quote",
            "mcp__stock-data-tools__get_stock_kline",
            "mcp__stock-data-tools__get_capital_flow",
            "mcp__stock-data-tools__get_orderbook",
            "mcp__stock-data-tools__get_stock_basicinfo"
        ]


class StockDataToolExecutor:
    """
    股票数据工具执行器
    负责执行AI调用的工具，从FutuMarket获取实际数据
    """

    def __init__(self, futu_market=None):
        """
        初始化工具执行器

        Args:
            futu_market: FutuMarket实例，用于获取股票数据
        """
        self.logger = get_logger(__name__)
        self.futu_market = futu_market

    def set_futu_market(self, futu_market):
        """设置FutuMarket实例"""
        self.futu_market = futu_market

    def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        执行指定的工具并返回结果

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数

        Returns:
            str: JSON格式的工具执行结果
        """
        try:
            if not self.futu_market:
                return json.dumps({"error": "FutuMarket未初始化，无法获取股票数据"}, ensure_ascii=False)

            if tool_name == "get_realtime_quote":
                return self._get_realtime_quote(tool_input)
            elif tool_name == "get_stock_kline":
                return self._get_stock_kline(tool_input)
            elif tool_name == "get_capital_flow":
                return self._get_capital_flow(tool_input)
            elif tool_name == "get_orderbook":
                return self._get_orderbook(tool_input)
            elif tool_name == "get_stock_basicinfo":
                return self._get_stock_basicinfo(tool_input)
            else:
                return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

        except Exception as e:
            self.logger.error(f"工具执行失败 {tool_name}: {e}")
            return json.dumps({"error": f"工具执行异常: {str(e)}"}, ensure_ascii=False)

    def _get_realtime_quote(self, tool_input: Dict[str, Any]) -> str:
        """获取实时行情"""
        stock_codes = tool_input.get("stock_codes", [])
        if not stock_codes:
            return json.dumps({"error": "缺少stock_codes参数"}, ensure_ascii=False)

        quotes = self.futu_market.get_stock_quote(stock_codes)
        if not quotes:
            return json.dumps({"error": "获取行情数据失败"}, ensure_ascii=False)

        # 转换为可序列化格式
        result = []
        for quote in quotes:
            if hasattr(quote, '__dict__'):
                result.append(quote.__dict__)
            elif isinstance(quote, dict):
                result.append(quote)
            else:
                result.append(str(quote))

        return json.dumps({"quotes": result}, ensure_ascii=False, default=str)

    def _get_stock_kline(self, tool_input: Dict[str, Any]) -> str:
        """获取K线数据"""
        stock_code = tool_input.get("stock_code", "")
        ktype = tool_input.get("ktype", "K_DAY")
        num = tool_input.get("num", 100)

        if not stock_code:
            return json.dumps({"error": "缺少stock_code参数"}, ensure_ascii=False)

        klines = self.futu_market.get_cur_kline([stock_code], num=num, ktype=ktype)
        if not klines:
            return json.dumps({"error": "获取K线数据失败"}, ensure_ascii=False)

        # 转换为可序列化格式
        result = []
        for kline in klines:
            if hasattr(kline, '__dict__'):
                result.append(kline.__dict__)
            elif isinstance(kline, dict):
                result.append(kline)
            else:
                result.append(str(kline))

        return json.dumps({"klines": result[-20:]}, ensure_ascii=False, default=str)  # 只返回最近20根K线

    def _get_capital_flow(self, tool_input: Dict[str, Any]) -> str:
        """获取资金流向"""
        stock_code = tool_input.get("stock_code", "")
        period_type = tool_input.get("period_type", "INTRADAY")

        if not stock_code:
            return json.dumps({"error": "缺少stock_code参数"}, ensure_ascii=False)

        flows = self.futu_market.get_capital_flow(stock_code, period_type)
        if not flows:
            return json.dumps({"error": "获取资金流向数据失败"}, ensure_ascii=False)

        # 转换为可序列化格式
        result = []
        for flow in flows:
            if hasattr(flow, '__dict__'):
                result.append(flow.__dict__)
            elif isinstance(flow, dict):
                result.append(flow)
            else:
                result.append(str(flow))

        return json.dumps({"capital_flow": result}, ensure_ascii=False, default=str)

    def _get_orderbook(self, tool_input: Dict[str, Any]) -> str:
        """获取五档买卖盘"""
        stock_code = tool_input.get("stock_code", "")

        if not stock_code:
            return json.dumps({"error": "缺少stock_code参数"}, ensure_ascii=False)

        orderbook = self.futu_market.get_order_book(stock_code)
        if not orderbook:
            return json.dumps({"error": "获取买卖盘数据失败"}, ensure_ascii=False)

        # 转换为可序列化格式
        if hasattr(orderbook, '__dict__'):
            result = orderbook.__dict__
        elif isinstance(orderbook, dict):
            result = orderbook
        else:
            result = str(orderbook)

        return json.dumps({"orderbook": result}, ensure_ascii=False, default=str)

    def _get_stock_basicinfo(self, tool_input: Dict[str, Any]) -> str:
        """获取股票基本信息"""
        stock_code = tool_input.get("stock_code", "")

        if not stock_code:
            return json.dumps({"error": "缺少stock_code参数"}, ensure_ascii=False)

        # 从股票代码提取市场
        if stock_code.startswith("HK."):
            market = "HK"
        elif stock_code.startswith("US."):
            market = "US"
        elif stock_code.startswith("SH."):
            market = "SH"
        elif stock_code.startswith("SZ."):
            market = "SZ"
        else:
            market = "HK"

        infos = self.futu_market.get_stock_basicinfo(market=market)
        if not infos:
            return json.dumps({"error": "获取股票基本信息失败"}, ensure_ascii=False)

        # 查找指定股票
        target_info = None
        for info in infos:
            info_code = info.get('code', '') if isinstance(info, dict) else getattr(info, 'code', '')
            if info_code == stock_code:
                target_info = info
                break

        if target_info:
            if hasattr(target_info, '__dict__'):
                result = target_info.__dict__
            elif isinstance(target_info, dict):
                result = target_info
            else:
                result = str(target_info)
            return json.dumps({"stock_info": result}, ensure_ascii=False, default=str)
        else:
            return json.dumps({"error": f"未找到股票 {stock_code} 的基本信息"}, ensure_ascii=False)


class ClaudeAIClient:
    """
    Claude AI客户端 - 基于Anthropic SDK
    支持完整的 tool use 能力，可动态调用股票数据API

    配置项 aibackend 支持以下值:
    - "anthropic": 强制使用 Anthropic SDK
    - "claude_code": 强制使用 claude-code-sdk
    - "auto": 自动选择（优先 Anthropic SDK）
    """

    # 支持的后端类型
    BACKEND_ANTHROPIC = "anthropic"
    BACKEND_CLAUDE_CODE = "claude_code"
    BACKEND_AUTO = "auto"

    def __init__(self, futu_market=None):
        """初始化Claude AI客户端"""
        self.logger = get_logger(__name__)
        self.config = get_config('Analyzer')

        # 初始化工具执行器
        self.tool_executor = StockDataToolExecutor(futu_market)

        # 初始化 MCP 服务器构建器（用于 claude-agent-sdk 的 tool use）
        self.mcp_server_builder = StockDataMCPServerBuilder(self.tool_executor)
        self.mcp_server = None  # 延迟创建

        # 从配置获取后端选择
        self.configured_backend = self._get_configured_backend()

        # 初始化Anthropic客户端
        self.anthropic_client = None
        self.anthropic_available = False

        # 初始化claude-code-sdk可用性和tool use支持
        self.claude_code_available = CLAUDE_CODE_SDK_AVAILABLE
        self.claude_code_tool_use_available = CLAUDE_AGENT_SDK_TOOL_SUPPORT

        # 根据配置初始化对应的SDK
        self._init_backend()

        # 确定主要可用方式
        self.available = self.anthropic_available or self.claude_code_available

        # 记录实际使用的后端
        self._log_backend_status()

    def _get_configured_backend(self) -> str:
        """从配置获取后端选择"""
        backend = self.config.get("aibackend", self.BACKEND_AUTO) if isinstance(self.config, dict) else self.BACKEND_AUTO
        backend = backend.lower().strip()

        # 验证配置值
        valid_backends = [self.BACKEND_ANTHROPIC, self.BACKEND_CLAUDE_CODE, self.BACKEND_AUTO]
        if backend not in valid_backends:
            self.logger.warning(f"无效的aibackend配置值: {backend}，使用默认值: auto")
            return self.BACKEND_AUTO

        return backend

    def _init_backend(self):
        """根据配置初始化对应的后端"""
        if self.configured_backend == self.BACKEND_ANTHROPIC:
            # 强制使用 Anthropic SDK
            self._init_anthropic_client()
            if not self.anthropic_available:
                self.logger.warning("配置要求使用Anthropic SDK，但初始化失败")
        elif self.configured_backend == self.BACKEND_CLAUDE_CODE:
            # 强制使用 claude-code-sdk，不初始化 Anthropic
            if not self.claude_code_available:
                self.logger.warning("配置要求使用claude-code-sdk，但SDK不可用")
        else:
            # auto 模式：都尝试初始化，优先 Anthropic
            self._init_anthropic_client()

    def _log_backend_status(self):
        """记录后端状态日志"""
        active_backend = self._get_active_backend()

        if active_backend == self.BACKEND_ANTHROPIC:
            self.logger.info(f"Claude AI客户端初始化成功 (配置: {self.configured_backend}, 使用: Anthropic SDK，支持tool use)")
        elif active_backend == self.BACKEND_CLAUDE_CODE:
            tool_use_status = "支持tool use (MCP)" if self.claude_code_tool_use_available else "不支持tool use"
            self.logger.info(f"Claude AI客户端初始化成功 (配置: {self.configured_backend}, 使用: claude-agent-sdk，{tool_use_status})")
        else:
            self.logger.error(f"Claude AI客户端不可用 (配置: {self.configured_backend})，请安装anthropic或claude-code-sdk")

    def _get_active_backend(self) -> Optional[str]:
        """获取当前实际使用的后端"""
        if self.configured_backend == self.BACKEND_ANTHROPIC:
            return self.BACKEND_ANTHROPIC if self.anthropic_available else None
        elif self.configured_backend == self.BACKEND_CLAUDE_CODE:
            return self.BACKEND_CLAUDE_CODE if self.claude_code_available else None
        else:
            # auto 模式：优先 Anthropic
            if self.anthropic_available:
                return self.BACKEND_ANTHROPIC
            elif self.claude_code_available:
                return self.BACKEND_CLAUDE_CODE
            return None

    def _init_anthropic_client(self):
        """初始化Anthropic客户端"""
        if not ANTHROPIC_SDK_AVAILABLE:
            self.logger.warning("anthropic SDK未安装")
            return

        try:
            # 从配置获取API Key (self.config 是字典，使用 get 方法的 default 参数)
            api_key = self.config.get("anthropicapikey", "") if isinstance(self.config, dict) else ""
            if not api_key:
                self.logger.warning("未配置AnthropicApiKey，无法使用Anthropic SDK")
                return

            self.anthropic_client = anthropic.Anthropic(api_key=api_key)
            self.anthropic_model = self.config.get("anthropicmodel", "claude-sonnet-4-20250514") if isinstance(self.config, dict) else "claude-sonnet-4-20250514"
            max_tokens_str = self.config.get("anthropicmaxtokens", "4096") if isinstance(self.config, dict) else "4096"
            self.anthropic_max_tokens = int(max_tokens_str) if max_tokens_str else 4096
            self.anthropic_available = True
            self.logger.info(f"Anthropic客户端初始化成功，模型: {self.anthropic_model}")

        except Exception as e:
            self.logger.error(f"Anthropic客户端初始化失败: {e}")
            self.anthropic_available = False

    def set_futu_market(self, futu_market):
        """设置FutuMarket实例，用于工具调用"""
        self.tool_executor.set_futu_market(futu_market)

    def is_available(self) -> bool:
        """检查Claude AI客户端是否可用"""
        return self.available

    def is_tool_use_available(self) -> bool:
        """检查是否支持tool use功能"""
        has_futu_market = self.tool_executor.futu_market is not None
        # Anthropic SDK 支持 tool use
        if self.anthropic_available and has_futu_market:
            return True
        # Claude Agent SDK 也支持 tool use (通过 MCP)
        if self.claude_code_available and self.claude_code_tool_use_available and has_futu_market:
            return True
        return False

    def _get_or_create_mcp_server(self):
        """获取或创建 MCP 服务器实例（延迟创建）"""
        if self.mcp_server is None and self.claude_code_tool_use_available:
            self.mcp_server = self.mcp_server_builder.create_mcp_server()
        return self.mcp_server

    def _call_anthropic_with_tools(self, system_prompt: str, user_message: str, use_tools: bool = True,
                                     progress_callback: callable = None) -> str:
        """
        使用Anthropic SDK调用API，支持工具调用循环

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            use_tools: 是否启用工具调用
            progress_callback: 进度回调函数，签名为 callback(event_type: str, data: dict)
                              event_type 可为: 'tool_start', 'tool_end', 'thinking', 'response'

        Returns:
            str: AI响应文本
        """
        self.logger.info(f"[TOOL-USE] ========== _call_anthropic_with_tools 开始 ==========")
        self.logger.info(f"[TOOL-USE] use_tools参数: {use_tools}")
        self.logger.info(f"[TOOL-USE] progress_callback: {'有' if progress_callback else '无'}")

        if not self.anthropic_available:
            self.logger.error("[TOOL-USE] Anthropic SDK不可用")
            raise RuntimeError("Anthropic SDK不可用")

        messages = [{"role": "user", "content": user_message}]

        # 决定是否使用工具
        tools = STOCK_DATA_TOOLS if use_tools and self.is_tool_use_available() else None
        self.logger.info(f"[TOOL-USE] 工具列表: {[t['name'] for t in tools] if tools else '无'}")
        self.logger.info(f"[TOOL-USE] 使用模型: {self.anthropic_model}, max_tokens: {self.anthropic_max_tokens}")

        max_iterations = 10  # 防止无限循环
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self.logger.info(f"[TOOL-USE] ===== 迭代 {iteration}/{max_iterations} =====")

            # 调用API
            try:
                self.logger.info(f"[TOOL-USE] 调用Anthropic API...")
                if tools:
                    response = self.anthropic_client.messages.create(
                        model=self.anthropic_model,
                        max_tokens=self.anthropic_max_tokens,
                        system=system_prompt,
                        tools=tools,
                        messages=messages
                    )
                else:
                    response = self.anthropic_client.messages.create(
                        model=self.anthropic_model,
                        max_tokens=self.anthropic_max_tokens,
                        system=system_prompt,
                        messages=messages
                    )
                self.logger.info(f"[TOOL-USE] API响应 stop_reason: {response.stop_reason}")
            except Exception as e:
                self.logger.error(f"[TOOL-USE] Anthropic API调用失败: {e}")
                raise

            # 检查是否需要处理工具调用
            if response.stop_reason == "tool_use":
                self.logger.info(f"[TOOL-USE] >>> 检测到工具调用请求 <<<")
                # 处理工具调用
                tool_results = []
                assistant_content = response.content

                for content_block in assistant_content:
                    if content_block.type == "tool_use":
                        tool_name = content_block.name
                        tool_input = content_block.input
                        tool_use_id = content_block.id

                        self.logger.info(f"[TOOL-USE] 工具名称: {tool_name}")
                        self.logger.info(f"[TOOL-USE] 工具输入: {tool_input}")
                        self.logger.info(f"[TOOL-USE] 工具ID: {tool_use_id}")

                        # 通知进度：工具调用开始
                        if progress_callback:
                            try:
                                progress_callback('tool_start', {
                                    'tool_name': tool_name,
                                    'tool_input': tool_input,
                                    'iteration': iteration
                                })
                            except Exception as cb_error:
                                self.logger.warning(f"[TOOL-USE] 进度回调失败: {cb_error}")

                        # 执行工具
                        self.logger.info(f"[TOOL-USE] 开始执行工具 {tool_name}...")
                        tool_result = self.tool_executor.execute_tool(tool_name, tool_input)

                        self.logger.info(f"[TOOL-USE] 工具执行完成，结果长度: {len(tool_result)}")
                        self.logger.debug(f"[TOOL-USE] 工具执行结果: {tool_result[:500]}...")

                        # 通知进度：工具调用结束
                        if progress_callback:
                            try:
                                progress_callback('tool_end', {
                                    'tool_name': tool_name,
                                    'tool_result_length': len(tool_result),
                                    'iteration': iteration
                                })
                            except Exception as cb_error:
                                self.logger.warning(f"[TOOL-USE] 进度回调失败: {cb_error}")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": tool_result
                        })

                # 将助手消息和工具结果添加到消息历史
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
                self.logger.info(f"[TOOL-USE] 已将工具结果添加到消息历史，继续对话...")

                # 通知进度：继续思考
                if progress_callback:
                    try:
                        progress_callback('thinking', {
                            'iteration': iteration,
                            'tools_called': [t['tool_use_id'] for t in tool_results]
                        })
                    except Exception as cb_error:
                        self.logger.warning(f"[TOOL-USE] 进度回调失败: {cb_error}")

            elif response.stop_reason == "end_turn":
                self.logger.info(f"[TOOL-USE] >>> 对话正常结束 <<<")
                # 正常结束，提取文本响应
                result_text = ""
                for content_block in response.content:
                    if hasattr(content_block, 'text'):
                        result_text += content_block.text

                self.logger.info(f"[TOOL-USE] 最终响应长度: {len(result_text)}")
                return result_text

            else:
                # 其他停止原因
                self.logger.warning(f"[TOOL-USE] 未预期的停止原因: {response.stop_reason}")
                result_text = ""
                for content_block in response.content:
                    if hasattr(content_block, 'text'):
                        result_text += content_block.text
                return result_text

        # 超过最大迭代次数
        self.logger.warning(f"[TOOL-USE] 工具调用循环超过最大次数 {max_iterations}")
        return "分析过程超时，请稍后重试"

    async def _call_anthropic_with_tools_async(self, system_prompt: str, user_message: str, use_tools: bool = True,
                                                progress_callback: callable = None) -> str:
        """
        异步版本的Anthropic API调用，支持工具调用循环

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            use_tools: 是否启用工具调用
            progress_callback: 进度回调函数（同步函数，会在executor中调用）

        Returns:
            str: AI响应文本
        """
        # 使用线程池执行同步调用
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._call_anthropic_with_tools(system_prompt, user_message, use_tools, progress_callback)
        )

    async def generate_stock_analysis(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """生成股票分析，支持工具调用获取实时数据"""
        try:
            if not self.is_available():
                return self._create_error_response(request, "Claude AI客户端不可用")

            self.logger.info(f"开始生成{request.analysis_type}分析: {request.stock_code}")

            # 根据配置选择后端
            active_backend = self._get_active_backend()
            if active_backend == self.BACKEND_ANTHROPIC:
                response_content = await self._generate_analysis_with_anthropic(request)
            elif active_backend == self.BACKEND_CLAUDE_CODE:
                response_content = await self._generate_analysis_with_claude_code(request)
            else:
                return self._create_error_response(request, "无可用的AI后端")

            if not response_content:
                return self._create_error_response(request, "Claude API调用失败")

            # 解析响应
            analysis_response = self._parse_analysis_response(request, response_content)

            self.logger.info(f"股票分析生成完成: {request.stock_code}, 类型: {request.analysis_type}")
            return analysis_response

        except Exception as e:
            self.logger.error(f"生成股票分析失败: {e}")
            return self._create_error_response(request, f"分析生成错误: {str(e)}")

    async def _generate_analysis_with_anthropic(self, request: AIAnalysisRequest) -> str:
        """使用Anthropic SDK生成分析（支持tool use）"""
        system_prompt = f"""你是一位专业的股票分析师AI助手，擅长技术分析和基本面分析。

你可以使用以下工具获取股票数据：
- get_realtime_quote: 获取实时行情报价
- get_stock_kline: 获取K线数据用于技术分析
- get_capital_flow: 获取资金流向数据
- get_orderbook: 获取五档买卖盘数据
- get_stock_basicinfo: 获取股票基本信息

请根据用户需求调用相关工具获取数据，然后进行专业分析。用中文回答。"""

        # 构建用户消息
        prompt = self._build_analysis_prompt_for_tool_use(request)
        self.logger.debug(f"分析提示词: {prompt}")

        try:
            # 使用支持工具调用的API
            response = await self._call_anthropic_with_tools_async(
                system_prompt=system_prompt,
                user_message=prompt,
                use_tools=self.is_tool_use_available()
            )
            return response
        except Exception as e:
            self.logger.error(f"Anthropic API调用失败: {e}")
            raise

    def _build_analysis_prompt_for_tool_use(self, request: AIAnalysisRequest) -> str:
        """为工具调用模式构建分析提示词"""
        prompt = f"""请对股票 {request.stock_code} 进行{self._get_analysis_type_name(request.analysis_type)}。

分析要求:
1. 首先使用工具获取该股票的实时行情、K线数据和资金流向
2. 结合技术指标（均线、RSI、MACD等）进行技术面分析
3. 分析资金流向判断主力动向
4. 分析五档买卖盘判断短期买卖力量
5. 提供明确的分析结论和投资建议
6. 评估风险等级和置信度"""

        # 添加用户已提供的上下文数据
        existing_context = self._build_existing_context(request)
        if existing_context:
            prompt += f"\n\n已有数据参考:\n{existing_context}"

        if request.user_input:
            prompt += f"\n\n用户特别关心的问题: {request.user_input}"

        return prompt

    def _build_existing_context(self, request: AIAnalysisRequest) -> str:
        """从request中提取已有的上下文数据"""
        context_parts = []

        realtime_quote = request.get_realtime_quote()
        if realtime_quote:
            context_parts.append(f"当前价格: {realtime_quote.get('cur_price', 0)}, 涨跌幅: {realtime_quote.get('change_rate', 0)}%")

        technical = request.get_technical_indicators()
        if technical:
            context_parts.append(f"技术指标: MA5={technical.get('ma5', 0)}, RSI={technical.get('rsi', 0)}")

        return "\n".join(context_parts) if context_parts else ""

    async def _generate_analysis_with_claude_code(self, request: AIAnalysisRequest) -> str:
        """使用claude-agent-sdk生成分析（支持 MCP tool use）"""
        # 如果支持 tool use，使用工具调用模式
        use_tools = self.claude_code_tool_use_available and self.tool_executor.futu_market is not None

        if use_tools:
            prompt = self._build_analysis_prompt_for_tool_use(request)
            system_prompt = """你是一位专业的股票分析师AI助手，擅长技术分析和基本面分析。

你可以使用以下工具获取股票数据：
- get_realtime_quote: 获取实时行情报价
- get_stock_kline: 获取K线数据用于技术分析
- get_capital_flow: 获取资金流向数据
- get_orderbook: 获取五档买卖盘数据
- get_stock_basicinfo: 获取股票基本信息

请根据用户需求调用相关工具获取数据，然后进行专业分析。用中文回答。"""
        else:
            prompt = self._build_analysis_prompt(request)
            system_prompt = "你是一位专业的股票分析师AI助手。请直接回复，不要使用任何工具。"

        self.logger.debug(f"分析提示词: {prompt}")
        return await self._query_claude_code_sdk(prompt, system_prompt, use_tools=use_tools)

    async def _query_claude_code_sdk(self, prompt: str, system_prompt: str = None, use_tools: bool = False) -> str:
        """统一的claude-code-sdk/claude-agent-sdk查询方法

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            use_tools: 是否使用工具（需要 claude-agent-sdk 支持）

        Returns:
            str: AI响应文本
        """
        if not CLAUDE_CODE_SDK_AVAILABLE or not query:
            raise RuntimeError("claude-code-sdk/claude-agent-sdk不可用")

        options = None
        mcp_servers = None
        allowed_tools = []

        # 如果启用工具且支持 MCP
        if use_tools and self.claude_code_tool_use_available and self.tool_executor.futu_market is not None:
            mcp_server = self._get_or_create_mcp_server()
            if mcp_server:
                mcp_servers = {"stock-data-tools": mcp_server}
                allowed_tools = StockDataMCPServerBuilder.get_allowed_tools()
                self.logger.info(f"claude-agent-sdk 启用 tool use，工具: {allowed_tools}")

        if ClaudeCodeOptions:
            options_kwargs = {
                "max_turns": 10 if use_tools else 1,
            }
            if system_prompt:
                options_kwargs["system_prompt"] = system_prompt
            if mcp_servers:
                options_kwargs["mcp_servers"] = mcp_servers
            if allowed_tools:
                options_kwargs["allowed_tools"] = allowed_tools
            options = ClaudeCodeOptions(**options_kwargs)

        response_content = ""
        try:
            query_iter = query(prompt=prompt, options=options) if options else query(prompt=prompt)
            async for message in query_iter:
                if SystemMessage and isinstance(message, SystemMessage):
                    continue
                if ResultMessage and isinstance(message, ResultMessage):
                    # 从 ResultMessage 中提取结果
                    if hasattr(message, 'result') and message.result:
                        response_content = str(message.result)
                    continue
                if AssistantMessage and isinstance(message, AssistantMessage):
                    if hasattr(message, 'content') and message.content:
                        for content_block in message.content:
                            if hasattr(content_block, 'text'):
                                response_content += content_block.text
                elif isinstance(message, str):
                    response_content += message
                elif hasattr(message, 'content'):
                    response_content += str(message.content)
                elif hasattr(message, 'result'):
                    response_content = str(message.result)
                else:
                    # 跳过其他类型的消息（如工具调用消息）
                    self.logger.debug(f"跳过消息类型: {type(message)}")
        except Exception as query_error:
            self.logger.error(f"claude-agent-sdk查询异常: {query_error}")
            raise

        return response_content
    
    async def chat_with_ai(self, user_message: str, stock_context: Dict[str, Any] = None, use_tools: bool = True,
                           progress_callback: callable = None) -> str:
        """与AI进行对话交互，支持工具调用获取实时数据

        Args:
            user_message: 用户消息
            stock_context: 股票上下文信息
            use_tools: 是否启用工具调用（默认True）
            progress_callback: 进度回调函数，签名为 callback(event_type: str, data: dict)
                              event_type 可为: 'tool_start', 'tool_end', 'thinking', 'response'

        Returns:
            str: AI响应文本
        """
        self.logger.info(f"[CHAT] ========== chat_with_ai 开始 ==========")
        self.logger.info(f"[CHAT] 用户消息: {user_message[:100]}...")
        self.logger.info(f"[CHAT] use_tools参数: {use_tools}")
        self.logger.info(f"[CHAT] tool_use可用性: {self.is_tool_use_available()}")
        self.logger.info(f"[CHAT] futu_market已设置: {self.tool_executor.futu_market is not None}")
        self.logger.info(f"[CHAT] progress_callback: {'有' if progress_callback else '无'}")

        try:
            if not self.is_available():
                self.logger.warning("[CHAT] AI服务不可用")
                return "抱歉，AI服务当前不可用，请稍后重试。"

            # 根据配置选择后端
            active_backend = self._get_active_backend()
            self.logger.info(f"[CHAT] 选择后端: {active_backend}")

            if active_backend == self.BACKEND_ANTHROPIC:
                self.logger.info("[CHAT] 使用 Anthropic SDK 进行对话")
                return await self._chat_with_anthropic(user_message, stock_context, use_tools, progress_callback)
            elif active_backend == self.BACKEND_CLAUDE_CODE:
                self.logger.info("[CHAT] 使用 claude-code-sdk 进行对话")
                return await self._chat_with_claude_code(user_message, stock_context, use_tools)
            else:
                self.logger.warning("[CHAT] 无可用后端")
                return "抱歉，AI服务当前不可用，请稍后重试。"

        except Exception as e:
            self.logger.error(f"[CHAT] AI对话失败: {e}")
            import traceback
            self.logger.error(f"[CHAT] 错误堆栈: {traceback.format_exc()}")
            return f"对话过程中出现错误: {str(e)}"

    async def _chat_with_anthropic(self, user_message: str, stock_context: Dict[str, Any] = None, use_tools: bool = True,
                                    progress_callback: callable = None) -> str:
        """使用Anthropic SDK进行对话（支持tool use）"""
        self.logger.info(f"[TOOL-USE] ========== _chat_with_anthropic 开始 ==========")

        system_prompt = """你是一位专业的股票分析师AI助手，具有丰富的投资分析经验。请用中文与用户交流。

你可以使用以下工具获取股票数据：
- get_realtime_quote: 获取实时行情报价
- get_stock_kline: 获取K线数据用于技术分析
- get_capital_flow: 获取资金流向数据
- get_orderbook: 获取五档买卖盘数据
- get_stock_basicinfo: 获取股票基本信息

当用户询问特定股票时，请主动调用相关工具获取最新数据，然后进行专业分析回答。"""

        # 构建用户消息
        prompt = self._build_chat_prompt(user_message, stock_context)
        self.logger.info(f"[TOOL-USE] 构建的prompt长度: {len(prompt)}")
        self.logger.debug(f"[TOOL-USE] prompt内容: {prompt[:500]}...")

        # 判断是否启用工具
        actual_use_tools = use_tools and self.is_tool_use_available()
        self.logger.info(f"[TOOL-USE] use_tools={use_tools}, is_tool_use_available={self.is_tool_use_available()}, 最终启用工具={actual_use_tools}")

        try:
            self.logger.info(f"[TOOL-USE] 调用 _call_anthropic_with_tools_async...")
            response = await self._call_anthropic_with_tools_async(
                system_prompt=system_prompt,
                user_message=prompt,
                use_tools=actual_use_tools,
                progress_callback=progress_callback
            )
            self.logger.info(f"[TOOL-USE] 收到响应，长度: {len(response) if response else 0}")
            return response if response else "抱歉，AI服务响应异常，请稍后重试。"
        except Exception as e:
            self.logger.error(f"[TOOL-USE] Anthropic对话异常: {e}")
            import traceback
            self.logger.error(f"[TOOL-USE] 错误堆栈: {traceback.format_exc()}")
            return f"对话服务异常: {str(e)}"

    async def _chat_with_claude_code(self, user_message: str, stock_context: Dict[str, Any] = None, use_tools: bool = True) -> str:
        """使用claude-agent-sdk进行对话（支持 MCP tool use）"""
        prompt = self._build_chat_prompt(user_message, stock_context)

        # 如果支持 tool use 且用户启用
        should_use_tools = use_tools and self.claude_code_tool_use_available and self.tool_executor.futu_market is not None

        if should_use_tools:
            system_prompt = """你是一位专业的股票分析师AI助手，具有丰富的投资分析经验。请用中文与用户交流。

你可以使用以下工具获取股票数据：
- get_realtime_quote: 获取实时行情报价
- get_stock_kline: 获取K线数据用于技术分析
- get_capital_flow: 获取资金流向数据
- get_orderbook: 获取五档买卖盘数据
- get_stock_basicinfo: 获取股票基本信息

当用户询问特定股票时，请主动调用相关工具获取最新数据，然后进行专业分析回答。"""
        else:
            system_prompt = "你是一位专业的股票分析师AI助手，具有丰富的投资分析经验。请用中文与用户交流，请直接回复。"

        try:
            response_content = await self._query_claude_code_sdk(prompt, system_prompt, use_tools=should_use_tools)
            return response_content if response_content else "抱歉，AI服务响应异常，请稍后重试。"
        except Exception as query_error:
            self.logger.error(f"Chat query调用异常: {query_error}")
            return f"对话服务异常: {str(query_error)}"

    async def generate_trading_advice(self, request: AITradingAdviceRequest) -> TradingAdvice:
        """根据用户输入生成交易建议，支持工具调用获取实时数据

        Args:
            request: AI交易建议请求对象

        Returns:
            TradingAdvice: 交易建议对象
        """
        try:
            if not self.is_available():
                return self._create_error_advice(request.user_input, "AI服务不可用")

            self.logger.info(f"开始生成交易建议: {request.user_input}")

            # 根据配置选择后端
            active_backend = self._get_active_backend()
            if active_backend == self.BACKEND_ANTHROPIC:
                ai_response = await self._generate_advice_with_anthropic(request)
            else:
                # 备选方案：使用chat_with_ai (包括 claude_code 模式)
                advice_prompt = self._build_advice_prompt(request)
                self.logger.debug(f"用户PROMPT: {advice_prompt}")
                ai_response = await self.chat_with_ai(advice_prompt, use_tools=False)

            # 解析AI响应为交易建议
            trading_advice = self._parse_advice_response(request, ai_response)

            self.logger.info(f"交易建议生成完成: {request.user_input} -> {trading_advice.advice_id}")
            return trading_advice

        except Exception as e:
            self.logger.error(f"生成交易建议失败: {e}")
            return self._create_error_advice(request.user_input, f"建议生成失败: {str(e)}")

    async def _generate_advice_with_anthropic(self, request: AITradingAdviceRequest) -> str:
        """使用Anthropic SDK生成交易建议（支持tool use）"""
        system_prompt = """你是一位专业的股票投资顾问AI助手，具有丰富的投资分析经验和风险管理能力。

你可以使用以下工具获取股票数据：
- get_realtime_quote: 获取实时行情报价
- get_stock_kline: 获取K线数据用于技术分析
- get_capital_flow: 获取资金流向数据
- get_orderbook: 获取五档买卖盘数据
- get_stock_basicinfo: 获取股票基本信息

请根据用户需求和市场情况，主动调用工具获取最新数据，然后生成专业的交易建议。
所有建议必须基于风险控制原则，考虑用户的风险偏好和资金状况。
用中文回答。"""

        # 构建用户消息
        advice_prompt = self._build_advice_prompt(request)
        self.logger.debug(f"用户PROMPT: {advice_prompt}")

        try:
            response = await self._call_anthropic_with_tools_async(
                system_prompt=system_prompt,
                user_message=advice_prompt,
                use_tools=self.is_tool_use_available()
            )
            return response
        except Exception as e:
            self.logger.error(f"Anthropic交易建议生成异常: {e}")
            raise

    async def confirm_and_execute_advice(self, advice: TradingAdvice, trade_manager=None, trd_env="SIMULATE") -> Dict[str, Any]:
        """确认并执行交易建议"""
        try:
            if advice.status != "pending":
                return {
                    "success": False,
                    "error": f"建议状态无效: {advice.status}，只能执行待确认的建议"
                }

            if not advice.suggested_orders:
                return {
                    "success": False,
                    "error": "建议中没有具体的交易订单"
                }

            # 标记为已确认
            advice.status = "confirmed"

            execution_results = []

            # 执行所有建议的订单
            for order in advice.suggested_orders:
                if trade_manager:
                    try:
                        self.logger.info(f"准备执行订单: {order.stock_code} {order.action} {order.quantity}")
                        # 调用交易管理器执行订单
                        result = trade_manager.place_order(
                            code=order.stock_code,
                            price=order.price or 0.0,
                            qty=order.quantity,
                            order_type=order.order_type,
                            trd_side=order.action.upper(),
                            aux_price=order.trigger_price,
                            trd_env=trd_env,  # 使用传入的交易环境参数
                            market=self._extract_market_from_code(order.stock_code)
                        )

                        execution_results.append({
                            "order": order,
                            "success": True,
                            "result": result
                        })

                        self.logger.info(f"订单执行成功: {order.stock_code} {order.action} {order.quantity}")

                    except Exception as order_error:
                        execution_results.append({
                            "order": order,
                            "success": False,
                            "error": str(order_error)
                        })

                        self.logger.error(f"订单执行失败: {order_error}")
                else:
                    # 没有交易管理器，无法执行订单
                    execution_results.append({
                        "order": order,
                        "success": False,
                        "error": f"交易管理器未提供，无法执行 {trd_env} 环境的交易"
                    })

            # 检查是否所有订单都成功
            all_success = all(result["success"] for result in execution_results)

            if all_success:
                advice.status = "executed"
            else:
                advice.status = "partial_executed"

            return {
                "success": all_success,
                "advice_id": advice.advice_id,
                "execution_results": execution_results,
                "status": advice.status
            }

        except Exception as e:
            self.logger.error(f"执行交易建议失败: {e}")
            advice.status = "error"
            return {
                "success": False,
                "error": f"执行过程异常: {str(e)}"
            }

    async def parse_trading_command(self, user_input: str, context: Dict[str, Any] = None) -> TradingOrder:
        """解析用户交易指令并转换为交易订单"""
        try:
            if not self.is_available():
                return TradingOrder(
                    stock_code="",
                    action="",
                    quantity=0,
                    confidence=0.0,
                    warnings=["AI服务不可用"]
                )

            # 构建解析提示词
            prompt = self._build_parsing_prompt(user_input, context or {})

            # 调用AI进行解析
            ai_response = await self.chat_with_ai(prompt)

            # 解析AI响应
            trading_order = self._parse_ai_response(ai_response)

            # 基础验证
            self._validate_order(trading_order)

            self.logger.info(f"交易指令解析完成: {user_input} -> {trading_order}")
            return trading_order

        except Exception as e:
            self.logger.error(f"交易指令解析失败: {e}")
            return TradingOrder(
                stock_code="",
                action="",
                quantity=0,
                confidence=0.0,
                warnings=[f"解析失败: {str(e)}"]
            )
    
    def _build_analysis_prompt(self, request: AIAnalysisRequest) -> str:
        """构建分析提示词

        Args:
            request: AI分析请求对象（使用统一的AIRequest基类）

        Returns:
            str: 格式化的分析提示词
        """
        try:
            # 使用统一的上下文获取方法
            basic_info = request.get_basic_info()
            realtime_quote = request.get_realtime_quote()
            technical_indicators = request.get_technical_indicators()
            capital_flow = request.get_capital_flow()
            orderbook = request.get_orderbook()

            # 基础分析模板
            prompt = f"""你是一位专业的股票分析师，请对股票 {request.stock_code} 进行{self._get_analysis_type_name(request.analysis_type)}。

股票数据:"""

            # 添加基本信息
            if basic_info:
                prompt += f"""
基本信息:
- 股票代码: {basic_info.get('code', request.stock_code)}
- 股票名称: {request.get_stock_name()}
- 股票类型: {basic_info.get('stock_type', '未知')}"""

            # 添加实时报价
            if realtime_quote:
                prompt += f"""
实时报价:
- 当前价格: {realtime_quote.get('cur_price', 0):.2f}
- 涨跌幅: {realtime_quote.get('change_rate', 0):+.2f}%
- 成交量: {realtime_quote.get('volume', 0):,}
- 换手率: {realtime_quote.get('turnover_rate', 0):.2f}%"""

            # 添加技术指标
            if technical_indicators:
                macd_data = technical_indicators.get('macd', {})
                prompt += f"""
技术指标:
- 均线: MA5={technical_indicators.get('ma5', 0):.2f}, MA10={technical_indicators.get('ma10', 0):.2f}, MA20={technical_indicators.get('ma20', 0):.2f}, MA60={technical_indicators.get('ma60', 0):.2f}
- RSI(14): {technical_indicators.get('rsi', 0):.1f}
- MACD: DIF={macd_data.get('dif', 0):.3f}, DEA={macd_data.get('dea', 0):.3f}, 柱状图={macd_data.get('histogram', 0):.3f}"""

            # 添加资金流向
            if capital_flow:
                main_flow = capital_flow.get('main_in_flow', 0)
                flow_direction = "流入" if main_flow > 0 else "流出"
                prompt += f"""
资金流向:
- 主力净{flow_direction}: {abs(main_flow):.2f}
- 超大单: {capital_flow.get('super_in_flow', 0):+.2f}, 大单: {capital_flow.get('big_in_flow', 0):+.2f}
- 中单: {capital_flow.get('mid_in_flow', 0):+.2f}, 小单: {capital_flow.get('sml_in_flow', 0):+.2f}"""

            # 添加五档买卖盘
            if orderbook:
                ask_data = orderbook.get('ask', [])
                bid_data = orderbook.get('bid', [])
                if ask_data or bid_data:
                    prompt += "\n五档买卖盘:"
                    if ask_data:
                        prompt += "\n- 卖盘: "
                        ask_items = []
                        for i, ask in enumerate(ask_data[:5], 1):
                            price = ask.get('price', 0)
                            volume = ask.get('volume', 0)
                            if price > 0:
                                ask_items.append(f"卖{i}={price:.2f}({volume})")
                        prompt += ", ".join(ask_items) if ask_items else "无数据"
                    if bid_data:
                        prompt += "\n- 买盘: "
                        bid_items = []
                        for i, bid in enumerate(bid_data[:5], 1):
                            price = bid.get('price', 0)
                            volume = bid.get('volume', 0)
                            if price > 0:
                                bid_items.append(f"买{i}={price:.2f}({volume})")
                        prompt += ", ".join(bid_items) if bid_items else "无数据"

            # 添加分析要求
            prompt += f"""

请进行{self._get_analysis_type_name(request.analysis_type)}，用中文回答，格式要求:
- 结合技术指标和资金流向进行综合分析
- 分析五档买卖盘判断短期买卖力量对比
- 提供明确的分析结论
- 给出投资建议和风险评估
- 评估置信度和风险等级"""

            # 添加用户问题（使用统一的user_input字段）
            if request.user_input:
                prompt += f"\n\n用户特别关心的问题: {request.user_input}\n请在分析中特别回答这个问题。"

            return prompt

        except Exception as e:
            self.logger.error(f"构建分析提示词失败: {e}")
            return f"分析股票 {request.stock_code} 的{self._get_analysis_type_name(request.analysis_type)}"
    
    def _build_chat_prompt(self, user_message: str, stock_context: Dict[str, Any] = None) -> str:
        """构建对话提示词"""
        prompt = f"用户问题: {user_message}"
        
        # 添加股票上下文
        if stock_context:
            context_info = ""
            if 'stock_code' in stock_context:
                context_info += f"股票代码: {stock_context['stock_code']}\n"
            if 'stock_name' in stock_context:
                context_info += f"股票名称: {stock_context['stock_name']}\n"
            if 'current_price' in stock_context:
                context_info += f"当前价格: {stock_context['current_price']}\n"
            
            if context_info:
                prompt = f"股票信息:\n{context_info}\n{prompt}"
        
        return prompt
    
    def _parse_analysis_response(self, request: AIAnalysisRequest, response: str) -> AIAnalysisResponse:
        """解析分析响应"""
        try:
            # 提取关键点
            key_points = self._extract_key_points(response)
            
            # 提取建议
            recommendation = self._extract_recommendation(response)
            
            # 评估置信度和风险等级
            confidence_score = self._estimate_confidence(response)
            risk_level = self._estimate_risk_level(response)
            
            return AIAnalysisResponse(
                request_id=f"{request.stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                stock_code=request.stock_code,
                analysis_type=request.analysis_type,
                content=response,
                key_points=key_points,
                recommendation=recommendation,
                confidence_score=confidence_score,
                risk_level=risk_level,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            self.logger.error(f"解析分析响应失败: {e}")
            return self._create_error_response(request, f"响应解析错误: {str(e)}")
    
    def _extract_key_points(self, response: str) -> List[str]:
        """从响应中提取关键点"""
        try:
            key_points = []
            lines = response.split('\n')
            
            for line in lines:
                line = line.strip()
                if (line.startswith('•') or line.startswith('-') or 
                    line.startswith('*') or '关键' in line or '重要' in line):
                    key_points.append(line.lstrip('•-*').strip())
            
            return key_points[:5]  # 最多返回5个关键点
            
        except Exception as e:
            self.logger.error(f"提取关键点失败: {e}")
            return []
    
    def _extract_recommendation(self, response: str) -> str:
        """从响应中提取投资建议"""
        try:
            recommendation_keywords = ['建议', '推荐', '操作', '策略', '投资']
            lines = response.split('。')
            
            for line in lines:
                if any(keyword in line for keyword in recommendation_keywords):
                    return line.strip()
            
            # 如果没找到特定建议，返回最后一段
            paragraphs = response.split('\n\n')
            if paragraphs:
                return paragraphs[-1].strip()
            
            return "请根据个人风险承受能力谨慎投资"
            
        except Exception as e:
            self.logger.error(f"提取投资建议失败: {e}")
            return "投资建议提取失败"

    def _build_parsing_prompt(self, user_input: str, context: Dict[str, Any]) -> str:
        """构建AI解析提示词"""
        return f"""
你是一个专业的股票交易指令解析器。请将用户的自然语言指令转换为结构化的交易订单。

用户指令: {user_input}

当前上下文:
- 当前选择股票: {context.get('current_stock', '无')}
- 当前股价: {context.get('current_price', '未知')}
- 可用资金: {context.get('available_funds', '未知')}

请按以下JSON格式返回解析结果:
{{
    "stock_code": "股票代码 (如HK.00700)",
    "action": "buy或sell",
    "quantity": 数量(整数),
    "price": 价格(数字,null表示市价),
    "order_type": "MARKET, NORMAL, STOP, STOP_LIMIT其中之一",
    "trigger_price": 触发价格(数字,仅止盈止损订单需要),
    "confidence": 0.0到1.0的置信度,
    "reasoning": "解析推理过程",
    "warnings": ["警告信息列表"]
}}

订单类型解析规则:
1. 现价订单 (MARKET): "市价买入"、"立即买入"、"现价卖出"等
2. 限价订单 (NORMAL): "420元买入"、"限价卖出450元"等
3. 止损订单 (STOP): "跌破400元止损"、"止损价设在380"等
4. 止盈限价订单 (STOP_LIMIT): "涨到500元止盈"、"止盈价设在480"等

通用解析规则:
1. 如果未明确指定股票，使用当前选择的股票
2. 如果未指定价格，默认为现价订单
3. 如果指令不明确，降低置信度并在warnings中说明
4. 仅支持买入(buy)和卖出(sell)操作
"""

    def _parse_ai_response(self, ai_response: str) -> TradingOrder:
        """解析AI响应并提取交易参数"""
        try:
            # 尝试从响应中提取JSON
            json_str = self._extract_json_from_response(ai_response)
            if json_str:
                order_data = json.loads(json_str)

                return TradingOrder(
                    stock_code=order_data.get('stock_code', ''),
                    action=order_data.get('action', ''),
                    quantity=int(order_data.get('quantity', 0)),
                    price=order_data.get('price'),
                    order_type=order_data.get('order_type', 'MARKET'),
                    trigger_price=order_data.get('trigger_price'),
                    confidence=float(order_data.get('confidence', 0.0)),
                    reasoning=order_data.get('reasoning', ''),
                    warnings=order_data.get('warnings', [])
                )
            else:
                # 如果无法提取JSON，返回错误订单
                return TradingOrder(
                    stock_code="",
                    action="",
                    quantity=0,
                    confidence=0.0,
                    warnings=["AI响应格式无效，无法解析为交易订单"]
                )

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}")
            return TradingOrder(
                stock_code="",
                action="",
                quantity=0,
                confidence=0.0,
                warnings=[f"JSON格式错误: {str(e)}"]
            )
        except Exception as e:
            self.logger.error(f"AI响应解析失败: {e}")
            return TradingOrder(
                stock_code="",
                action="",
                quantity=0,
                confidence=0.0,
                warnings=[f"响应解析异常: {str(e)}"]
            )

    def _extract_json_from_response(self, response: str) -> Optional[str]:
        """从AI响应中提取JSON字符串，支持不完整JSON的修复"""
        try:
            # 查找JSON块
            start_markers = ['```json', '```', '{']

            # 查找JSON开始位置
            start_pos = -1
            for marker in start_markers:
                pos = response.find(marker)
                if pos != -1:
                    start_pos = pos + len(marker) if marker != '{' else pos
                    break

            if start_pos == -1:
                # 尝试查找第一个{
                start_pos = response.find('{')

            if start_pos == -1:
                return None

            # 查找JSON结束位置
            end_pos = -1
            if start_pos >= 0:
                # 从开始位置查找最后一个}
                remaining = response[start_pos:]
                last_brace = remaining.rfind('}')
                if last_brace != -1:
                    end_pos = start_pos + last_brace + 1

            if end_pos == -1:
                return None

            # 提取JSON字符串
            json_str = response[start_pos:end_pos].strip()

            # 清理可能的markdown标记
            if json_str.startswith('```json'):
                json_str = json_str[7:]
            if json_str.startswith('```'):
                json_str = json_str[3:]
            if json_str.endswith('```'):
                json_str = json_str[:-3]

            json_str = json_str.strip()

            # 尝试验证JSON是否完整，如果不完整则尝试修复
            json_str = self._try_fix_incomplete_json(json_str)

            return json_str

        except Exception as e:
            self.logger.error(f"提取JSON失败: {e}")
            return None

    def _try_fix_incomplete_json(self, json_str: str) -> str:
        """尝试修复不完整的JSON字符串

        Args:
            json_str: 可能不完整的JSON字符串

        Returns:
            str: 修复后的JSON字符串（如果无法修复则返回原始字符串）
        """
        try:
            # 首先尝试直接解析，如果成功则无需修复
            json.loads(json_str)
            return json_str
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON不完整，尝试修复: {e}")

        try:
            # 统计括号数量
            open_braces = json_str.count('{')
            close_braces = json_str.count('}')
            open_brackets = json_str.count('[')
            close_brackets = json_str.count(']')

            # 检查是否在字符串中间被截断（查找未闭合的引号）
            # 简单策略：如果最后一个非空白字符不是 } ] , 或数字，可能是字符串被截断
            stripped = json_str.rstrip()
            if stripped and stripped[-1] not in '}],0123456789nulltruefalse"':
                # 可能在字符串中间被截断，尝试找到最后一个完整的字段
                # 查找最后一个逗号或冒号后的完整值
                last_comma = stripped.rfind(',')
                last_colon = stripped.rfind(':')

                if last_colon > last_comma:
                    # 在值的中间被截断，截断到上一个逗号
                    if last_comma > 0:
                        json_str = stripped[:last_comma]
                        self.logger.info(f"截断不完整的字段，保留到位置 {last_comma}")

            # 重新统计括号
            open_braces = json_str.count('{')
            close_braces = json_str.count('}')
            open_brackets = json_str.count('[')
            close_brackets = json_str.count(']')

            # 添加缺失的闭合括号
            missing_brackets = open_brackets - close_brackets
            missing_braces = open_braces - close_braces

            if missing_brackets > 0 or missing_braces > 0:
                # 确保字符串末尾没有悬空的逗号
                json_str = json_str.rstrip().rstrip(',')

                # 如果末尾是未闭合的字符串，尝试闭合它
                if json_str.count('"') % 2 != 0:
                    json_str += '"'

                # 添加缺失的括号
                json_str += ']' * missing_brackets
                json_str += '}' * missing_braces

                self.logger.info(f"修复JSON: 添加了 {missing_brackets} 个 ] 和 {missing_braces} 个 }}")

            # 验证修复后的JSON
            try:
                json.loads(json_str)
                self.logger.info("JSON修复成功")
                return json_str
            except json.JSONDecodeError as e:
                self.logger.warning(f"JSON修复后仍无法解析: {e}")
                # 返回原始字符串，让调用方处理错误
                return json_str

        except Exception as e:
            self.logger.error(f"修复JSON时出错: {e}")
            return json_str

    def _validate_order(self, order: TradingOrder) -> None:
        """验证交易订单的基本有效性"""
        try:
            warnings = list(order.warnings) if order.warnings else []

            # 验证股票代码
            if not order.stock_code:
                warnings.append("缺少股票代码")

            # 验证买卖方向
            if order.action not in ['buy', 'sell']:
                warnings.append(f"无效的交易方向: {order.action}")

            # 验证数量
            if order.quantity <= 0:
                warnings.append(f"无效的交易数量: {order.quantity}")

            # 验证订单类型
            valid_types = [OrderType.MARKET, OrderType.NORMAL, OrderType.STOP, OrderType.STOP_LIMIT]
            if order.order_type not in valid_types:
                warnings.append(f"无效的订单类型: {order.order_type}")

            # 验证价格
            if order.order_type == OrderType.NORMAL and (order.price is None or order.price <= 0):
                warnings.append("限价订单必须指定有效价格")

            # 验证触发价格
            if order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT]:
                if order.trigger_price is None or order.trigger_price <= 0:
                    warnings.append("止损止盈订单必须指定有效触发价格")

            # 更新警告列表
            order.warnings = warnings

        except Exception as e:
            self.logger.error(f"订单验证失败: {e}")
            if not order.warnings:
                order.warnings = []
            order.warnings.append(f"验证过程异常: {str(e)}")

    def _build_advice_prompt(self, request: AITradingAdviceRequest) -> str:
        """构建AI建议生成提示词

        Args:
            request: AI交易建议请求对象

        Returns:
            str: 格式化的提示词
        """
        # 从统一的request对象中提取信息
        realtime_quote = request.get_realtime_quote()
        technical_indicators = request.get_technical_indicators()
        capital_flow = request.get_capital_flow()
        orderbook = request.get_orderbook()
        trading_mode = request.get_trading_mode()
        position_list = request.get_position_list()
        account_info = request.get_account_info()
        pending_orders = request.get_pending_orders()
        today_deals = request.get_today_deals()

        # 构建技术指标信息文本
        technical_info = ""
        if technical_indicators:
            technical_info = "\n技术指标数据:"

            # MA均线
            if 'ma5' in technical_indicators:
                technical_info += f"\n- MA5: {technical_indicators['ma5']:.2f}"
            if 'ma10' in technical_indicators:
                technical_info += f", MA10: {technical_indicators['ma10']:.2f}"
            if 'ma20' in technical_indicators:
                technical_info += f", MA20: {technical_indicators['ma20']:.2f}"
            if 'ma60' in technical_indicators:
                technical_info += f", MA60: {technical_indicators['ma60']:.2f}"

            # RSI指标
            if 'rsi' in technical_indicators:
                rsi_value = technical_indicators['rsi']
                technical_info += f"\n- RSI(14): {rsi_value:.1f}"

            # MACD指标
            if 'macd' in technical_indicators and isinstance(technical_indicators['macd'], dict):
                macd_data = technical_indicators['macd']
                dif = macd_data.get('dif', 0)
                dea = macd_data.get('dea', 0)
                histogram = macd_data.get('histogram', 0)
                technical_info += f"\n- MACD: DIF={dif:.3f}, DEA={dea:.3f}, 柱状图={histogram:.3f}"

        # 构建资金流向信息文本
        capital_flow_info = ""
        if capital_flow:
            capital_flow_info = "\n资金流向数据:"

            # 主力资金流向
            if 'main_in_flow' in capital_flow:
                main_flow = capital_flow['main_in_flow']
                flow_direction = "流入" if main_flow > 0 else "流出"
                capital_flow_info += f"\n- 主力净{flow_direction}: {abs(main_flow):.2f}"

            # 超大单、大单、中单、小单
            flow_types = [
                ('super_in_flow', '超大单'),
                ('big_in_flow', '大单'),
                ('mid_in_flow', '中单'),
                ('sml_in_flow', '小单')
            ]
            for flow_key, flow_label in flow_types:
                if flow_key in capital_flow:
                    flow_value = capital_flow[flow_key]
                    capital_flow_info += f", {flow_label}: {flow_value:+.2f}"

        # 构建五档买卖盘信息文本
        orderbook_info = ""
        if orderbook:
            ask_data = orderbook.get('ask', [])
            bid_data = orderbook.get('bid', [])
            if ask_data or bid_data:
                orderbook_info = "\n五档买卖盘:"
                if ask_data:
                    ask_items = []
                    for i, ask in enumerate(ask_data[:5], 1):
                        price = ask.get('price', 0)
                        volume = ask.get('volume', 0)
                        if price > 0:
                            ask_items.append(f"卖{i}={price:.2f}({volume})")
                    if ask_items:
                        orderbook_info += f"\n- 卖盘: {', '.join(ask_items)}"
                if bid_data:
                    bid_items = []
                    for i, bid in enumerate(bid_data[:5], 1):
                        price = bid.get('price', 0)
                        volume = bid.get('volume', 0)
                        if price > 0:
                            bid_items.append(f"买{i}={price:.2f}({volume})")
                    if bid_items:
                        orderbook_info += f"\n- 买盘: {', '.join(bid_items)}"

        # 构建账户资金信息文本
        account_info_text = ""
        if account_info:
            total_assets = account_info.get('total_assets', 0)
            cash = account_info.get('cash', 0)
            market_val = account_info.get('market_val', 0)
            currency = account_info.get('currency', 'HKD')
            account_info_text = f"\n账户资金({trading_mode}):"
            account_info_text += f"\n- 总资产: {total_assets:.2f} {currency}"
            account_info_text += f", 现金: {cash:.2f}, 持仓市值: {market_val:.2f}"

        # 构建持仓列表信息文本
        position_info_text = ""
        if position_list:
            position_info_text = f"\n持仓列表({len(position_list)}只股票):"
            for pos in position_list[:5]:  # 最多显示5只
                stock_code = pos.get('stock_code', '')
                stock_name = pos.get('stock_name', '')
                qty = pos.get('qty', 0)
                cost_price = pos.get('cost_price', 0)
                pl_ratio = pos.get('pl_ratio', 0)
                position_info_text += f"\n- {stock_code} {stock_name}: {qty}股, 成本{cost_price:.2f}, 盈亏{pl_ratio:+.2f}%"
            if len(position_list) > 5:
                position_info_text += f"\n- ... 还有{len(position_list) - 5}只股票"

        # 构建待成交订单信息文本
        pending_orders_text = ""
        if pending_orders:
            pending_orders_text = f"\n当日待成交订单({len(pending_orders)}笔):"
            for order in pending_orders[:5]:  # 最多显示5笔
                stock_code = order.get('stock_code', '')
                trd_side = "买入" if order.get('trd_side', '') == 'BUY' else "卖出"
                qty = order.get('qty', 0)
                price = order.get('price', 0)
                dealt_qty = order.get('dealt_qty', 0)
                create_time = order.get('create_time', '')
                pending_orders_text += f"\n- {stock_code} {trd_side} {qty}股@{price:.2f}, 已成交{dealt_qty}股, 时间{create_time}"
            if len(pending_orders) > 5:
                pending_orders_text += f"\n- ... 还有{len(pending_orders) - 5}笔订单"

        # 构建当日成交记录信息文本
        today_deals_text = ""
        if today_deals:
            today_deals_text = f"\n当日成交记录({len(today_deals)}笔):"
            for deal in today_deals[:5]:  # 最多显示5笔
                stock_code = deal.get('stock_code', '')
                trd_side = "买入" if deal.get('trd_side', '') == 'BUY' else "卖出"
                qty = deal.get('qty', 0)
                price = deal.get('price', 0)
                create_time = deal.get('create_time', '')
                today_deals_text += f"\n- {stock_code} {trd_side} {qty}股@{price:.2f}, 时间{create_time}"
            if len(today_deals) > 5:
                today_deals_text += f"\n- ... 还有{len(today_deals) - 5}笔成交"

        # 构建K线数据信息文本
        kline_data = request.get_kline_data()
        kline_info = ""
        if kline_data:
            kline_info = f"\n近期K线数据({len(kline_data)}根):"
            # 显示最近10根K线
            recent_klines = kline_data[-10:] if len(kline_data) > 10 else kline_data
            for kline in recent_klines:
                date = kline.get('time_key', kline.get('date', ''))
                open_price = kline.get('open', 0)
                high_price = kline.get('high', 0)
                low_price = kline.get('low', 0)
                close_price = kline.get('close', 0)
                volume = kline.get('volume', 0)
                change_rate = kline.get('change_rate', 0)
                # 格式化成交量
                if volume >= 100000000:
                    vol_str = f"{volume / 100000000:.2f}亿"
                elif volume >= 10000:
                    vol_str = f"{volume / 10000:.1f}万"
                else:
                    vol_str = str(volume)
                kline_info += f"\n- {date}: 开{open_price:.2f} 高{high_price:.2f} 低{low_price:.2f} 收{close_price:.2f} 量{vol_str} 涨跌{change_rate:+.2f}%"

        return f"""
你是一位专业的股票投资顾问AI助手。用户向你咨询投资建议，请根据用户的需求和当前市场情况，生成专业的交易建议。

用户需求: {request.user_input}

当前市场上下文:
- 当前关注股票: {request.stock_code}
- 股票名称: {request.get_stock_name()}
- 当前股价: {realtime_quote.get('cur_price', '未知')}
- 今日涨跌幅: {realtime_quote.get('change_rate', '未知')}
- 成交量: {realtime_quote.get('volume', '未知')}
- 交易模式: {trading_mode}
- 可用资金: {request.get_available_funds()}
- 当前股票持仓: {request.get_current_position()}
- 风险偏好: {request.risk_preference}
{account_info_text}{position_info_text}{pending_orders_text}{today_deals_text}{kline_info}{technical_info}{capital_flow_info}{orderbook_info}

请按以下JSON格式返回投资建议（务必确保JSON结构完整，所有括号正确闭合）:
{{
    "advice_summary": "简短的建议摘要（1-2句话，不超过100字）",
    "detailed_analysis": "简明扼要的分析要点（不超过300字，使用简洁的要点式描述）",
    "recommended_action": "buy, sell, hold, wait 其中之一",
    "suggested_orders": [
        {{
            "stock_code": "股票代码",
            "action": "buy或sell",
            "quantity": 建议数量,
            "price": 建议价格(null表示市价),
            "order_type": "MARKET, NORMAL, STOP, STOP_LIMIT其中之一",
            "trigger_price": 触发价格(可选),
            "reasoning": "订单原因（不超过50字）"
        }}
    ],
    "risk_assessment": "低, 中, 高 其中之一",
    "confidence_score": 0.0到1.0的置信度,
    "expected_return": "预期收益描述（不超过50字）",
    "risk_factors": ["风险因素1", "风险因素2"],
    "key_points": ["关键要点1", "关键要点2", "关键要点3"]
}}

重要提示：
- JSON结构完整性是最高优先级，务必确保所有括号正确闭合
- 所有字符串字段保持简洁，避免过长导致响应被截断
- 如果分析内容较多，优先保证JSON结构完整，可以精简文字描述

分析要求:
1. 结合当前股价、技术指标、资金流向和市场情况进行综合分析
2. 充分利用技术指标(MA、RSI、MACD等)进行技术面分析
3. 结合资金流向数据分析主力资金动向和市场情绪
4. 分析五档买卖盘数据判断短期买卖力量对比和支撑阻力位
5. 基于用户的实际持仓和可用资金制定合理的仓位建议,如果用户已持有该股票，考虑是加仓、减仓还是持有
8. 提供具体可执行的交易策略，建议数量应与可用资金匹配
9. 明确指出风险因素和注意事项
10. 如果市场条件不适合交易，建议等待.但是当用户提出建仓需求时,提出合理买入价格建议
11. 所有建议必须基于风险控制原则
12. 如果用户已有待成交订单，避免建议重复挂单，可建议修改或取消现有订单
13. 参考当日成交记录了解用户今日交易行为，避免频繁交易建议
14. 严进策略：不追高，乖离率 > 5% 不买入
16. 效率优先：关注筹码集中度好的股票
17. 买点偏好：缩量回踩 MA5/MA10 支撑 MA5>MA10>MA20 多头排列
回答请用中文，格式严格按照上述JSON结构。
"""

    def _parse_advice_response(self, request: AITradingAdviceRequest, ai_response: str) -> TradingAdvice:
        """解析AI响应为交易建议

        Args:
            request: AI交易建议请求对象
            ai_response: AI返回的响应文本

        Returns:
            TradingAdvice: 解析后的交易建议对象
        """
        try:
            # 调试日志：记录原始响应
            self.logger.debug(f"AI原始响应: {ai_response[:500]}...")

            # 提取JSON数据
            json_str = self._extract_json_from_response(ai_response)
            if json_str:
                self.logger.debug(f"提取的JSON字符串: {json_str[:500]}...")
                advice_data = json.loads(json_str)

                # 调试日志：记录解析后的数据
                self.logger.info(f"解析后的建议数据: recommended_action={advice_data.get('recommended_action')}, "
                               f"suggested_orders数量={len(advice_data.get('suggested_orders', []))}")

                # 解析建议的订单
                suggested_orders = []
                for order_data in advice_data.get('suggested_orders', []):
                    order = TradingOrder(
                        stock_code=order_data.get('stock_code', request.stock_code),
                        action=order_data.get('action', ''),
                        quantity=int(order_data.get('quantity', 0)),
                        price=order_data.get('price'),
                        order_type=order_data.get('order_type', 'MARKET'),
                        trigger_price=order_data.get('trigger_price'),
                        reasoning=order_data.get('reasoning', '')
                    )
                    # 验证订单
                    self._validate_order(order)
                    suggested_orders.append(order)

                # 如果没有订单但有recommended_action，记录警告
                if not suggested_orders and advice_data.get('recommended_action') not in ['wait', 'hold']:
                    self.logger.warning(f"AI建议操作为{advice_data.get('recommended_action')}但未提供具体订单！")

                # 生成建议ID
                advice_id = f"advice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(request.user_input) % 10000}"

                return TradingAdvice(
                    advice_id=advice_id,
                    user_prompt=request.user_input,
                    stock_code=request.stock_code,
                    stock_name=request.get_stock_name(),
                    advice_summary=advice_data.get('advice_summary', ''),
                    detailed_analysis=advice_data.get('detailed_analysis', ''),
                    recommended_action=advice_data.get('recommended_action', 'wait'),
                    suggested_orders=suggested_orders,
                    risk_assessment=advice_data.get('risk_assessment', '中'),
                    confidence_score=float(advice_data.get('confidence_score', 0.0)),
                    expected_return=advice_data.get('expected_return'),
                    risk_factors=advice_data.get('risk_factors', []),
                    key_points=advice_data.get('key_points', []),
                    status="pending"
                )
            else:
                # 无法解析JSON，创建基于文本的建议
                return self._create_text_based_advice(request, ai_response)

        except json.JSONDecodeError as e:
            self.logger.warning(f"建议JSON解析失败: {e}，降级为文本建议")
            # JSON解析失败时，降级为文本建议而不是错误建议
            return self._create_text_based_advice(request, ai_response)
        except Exception as e:
            self.logger.error(f"解析交易建议失败: {e}")
            return self._create_error_advice(request.user_input, f"建议解析异常: {str(e)}")

    def _create_text_based_advice(self, request: AITradingAdviceRequest, ai_response: str) -> TradingAdvice:
        """基于纯文本响应创建建议

        Args:
            request: AI交易建议请求对象
            ai_response: AI返回的文本响应

        Returns:
            TradingAdvice: 基于文本的建议对象
        """
        advice_id = f"text_advice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(request.user_input) % 10000}"

        return TradingAdvice(
            advice_id=advice_id,
            user_prompt=request.user_input,
            stock_code=request.stock_code,
            stock_name=request.get_stock_name(),
            advice_summary="AI提供了文本建议，请查看详细分析",
            detailed_analysis=ai_response,
            recommended_action="wait",
            suggested_orders=[],
            risk_assessment="中",
            confidence_score=0.5,
            expected_return="请参考详细分析",
            risk_factors=["AI响应格式不标准，请谨慎参考"],
            key_points=["请仔细阅读详细分析内容"],
            status="pending"
        )

    def _create_error_advice(self, user_prompt: str, error_message: str) -> TradingAdvice:
        """创建错误建议"""
        advice_id = f"error_advice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        return TradingAdvice(
            advice_id=advice_id,
            user_prompt=user_prompt,
            stock_code="",
            stock_name="",
            advice_summary=f"建议生成失败: {error_message}",
            detailed_analysis=f"由于技术问题无法生成投资建议: {error_message}",
            recommended_action="wait",
            suggested_orders=[],
            risk_assessment="高",
            confidence_score=0.0,
            expected_return="无法评估",
            risk_factors=["AI服务异常", "建议不可用"],
            key_points=["请稍后重试", "如有需要请咨询专业投资顾问"],
            status="error"
        )

    def _extract_market_from_code(self, stock_code: str) -> str:
        """从股票代码提取市场信息"""
        if stock_code.startswith('HK.'):
            return 'HK'
        elif stock_code.startswith('US.'):
            return 'US'
        elif stock_code.startswith(('SH.', 'SZ.')):
            return 'CN'
        else:
            return 'HK'  # 默认港股
    
    def _estimate_confidence(self, response: str) -> float:
        """估算分析置信度"""
        try:
            high_confidence_words = ['明确', '强烈', '确定', '显著', '明显']
            low_confidence_words = ['不确定', '谨慎', '观望', '等待', '可能']
            
            response_lower = response.lower()
            
            high_count = sum(1 for word in high_confidence_words if word in response_lower)
            low_count = sum(1 for word in low_confidence_words if word in response_lower)
            
            if high_count > low_count:
                return 0.8
            elif low_count > high_count:
                return 0.4
            else:
                return 0.6
                
        except Exception as e:
            self.logger.error(f"估算置信度失败: {e}")
            return 0.5
    
    def _estimate_risk_level(self, response: str) -> str:
        """估算风险等级"""
        try:
            response_lower = response.lower()
            
            high_risk_words = ['高风险', '风险较高', '谨慎', '风险', '波动大']
            low_risk_words = ['低风险', '稳健', '保守', '安全']
            
            high_risk_count = sum(1 for word in high_risk_words if word in response_lower)
            low_risk_count = sum(1 for word in low_risk_words if word in response_lower)
            
            if high_risk_count > low_risk_count:
                return '高'
            elif low_risk_count > high_risk_count:
                return '低'
            else:
                return '中'
                
        except Exception as e:
            self.logger.error(f"估算风险等级失败: {e}")
            return '中'
    
    def _create_error_response(self, request: AIAnalysisRequest, error_message: str) -> AIAnalysisResponse:
        """创建错误响应"""
        return AIAnalysisResponse(
            request_id=f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            stock_code=request.stock_code,
            analysis_type=request.analysis_type,
            content=f"分析过程中出现错误: {error_message}",
            key_points=[],
            recommendation="由于技术问题，建议稍后重试或咨询专业投资顾问",
            confidence_score=0.0,
            risk_level='未知',
            timestamp=datetime.now()
        )
    
    def _get_analysis_type_name(self, analysis_type: str) -> str:
        """获取分析类型中文名称"""
        type_names = {
            'technical': '技术分析',
            'fundamental': '基本面分析',
            'comprehensive': '综合分析',
            'risk_assessment': '风险评估',
            'capital_flow': '资金流向分析'
        }
        return type_names.get(analysis_type, '综合分析')
    
    def get_client_status(self) -> Dict[str, Any]:
        """获取客户端状态"""
        active_backend = self._get_active_backend()
        active_backend_name = None
        if active_backend == self.BACKEND_ANTHROPIC:
            active_backend_name = 'Anthropic SDK'
        elif active_backend == self.BACKEND_CLAUDE_CODE:
            active_backend_name = 'claude-agent-sdk'
        else:
            active_backend_name = 'Unavailable'

        return {
            'available': self.available,
            'configured_backend': self.configured_backend,
            'active_backend': active_backend_name,
            'anthropic_sdk_available': ANTHROPIC_SDK_AVAILABLE,
            'anthropic_client_ready': self.anthropic_available,
            'claude_code_sdk_available': self.claude_code_available,
            'claude_agent_sdk_tool_support': self.claude_code_tool_use_available,
            'tool_use_available': self.is_tool_use_available(),
            'model': getattr(self, 'anthropic_model', None) if self.anthropic_available else None
        }
    
    def test_connection(self) -> bool:
        """测试Claude AI连接

        Returns:
            bool: 连接是否可用
        """
        if self.anthropic_available and self.anthropic_client:
            try:
                # 尝试发送一个简单请求测试连接
                response = self.anthropic_client.messages.create(
                    model=self.anthropic_model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Say OK"}]
                )
                return response is not None
            except Exception as e:
                self.logger.warning(f"Anthropic连接测试失败: {e}")
                return False
        elif self.claude_code_available:
            # claude-code-sdk 无法简单测试连接，假设可用
            return True
        return False


# 便捷函数
async def create_claude_client() -> ClaudeAIClient:
    """创建Claude AI客户端的便捷函数"""
    client = ClaudeAIClient()
    
    if client.is_available():
        # 简化版本：只检查SDK可用性，避免异步任务冲突
        connection_ok = client.test_connection()
        if connection_ok:
            client.logger.info("Claude AI客户端就绪")
        else:
            client.logger.warning("Claude AI SDK不可用")
    
    return client


async def quick_stock_analysis(stock_code: str, analysis_type: str = 'comprehensive', 
                              data_context: Dict[str, Any] = None) -> str:
    """快速股票分析的便捷函数"""
    try:
        client = await create_claude_client()
        
        if not client.is_available():
            return "Claude AI服务不可用，请检查claude-code-sdk安装状态。"
        
        request = AIAnalysisRequest(
            stock_code=stock_code,
            analysis_type=analysis_type,
            data_context=data_context or {}
        )
        
        response = await client.generate_stock_analysis(request)
        return response.content
        
    except Exception as e:
        return f"快速分析失败: {str(e)}"