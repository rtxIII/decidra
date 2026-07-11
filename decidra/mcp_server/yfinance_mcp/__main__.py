"""yfinance MCP 服务器启动入口。

用法: ``python -m decidra.mcp_server.yfinance_mcp``（stdio 传输）。
"""

from .server import main

if __name__ == "__main__":
    main()
