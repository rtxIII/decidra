"""Decidra MCP 服务器包。

以 Model Context Protocol (stdio) 形式把 Decidra 的富途行情/交易能力暴露给
终端 agent。复用现有 ``FutuMarket`` / ``FutuTrade`` 封装，不重写富途逻辑。

启动: ``python -m decidra.mcp_server``
"""

__all__ = ["build_server"]


def build_server():
    """构建并返回富途 MCP 服务器（延迟导入，避免包导入即拉起富途依赖）。"""
    from .futu_server import build_server as _build
    return _build()
