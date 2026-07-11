"""yfinance MCP 服务器启动入口。

用法: ``python -m decidra.mcp_server.yfinance_mcp``（stdio 传输）。
"""

import os

from .server import main

if __name__ == "__main__":
    try:
        main()
    finally:
        # vendored server 有 60s 后台线程；父进程关闭 stdio 后强制退出，
        # 确保子进程被 openharness 干净回收，与 futu/czsc server 一致。
        os._exit(0)
