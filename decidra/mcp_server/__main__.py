"""富途 MCP 服务器启动入口。

用法: ``python -m decidra.mcp_server``（stdio 传输，供 MCP 客户端以子进程方式连接）。
"""

import os
import signal

from .futu_server import build_server


def _install_hard_exit_handlers() -> None:
    """父进程 terminate（SIGTERM/SIGINT）时立即硬退出。

    富途 SDK（FutuMarket）会创建非守护线程，阻止子进程正常退出；若不硬退出，
    openharness 父进程 close 时会长时间阻塞在等待子进程终止上。装信号处理器直接
    ``os._exit(0)``，使子进程被 terminate 时瞬间死亡，父进程 close 不再挂起。
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: os._exit(0))
        except (ValueError, OSError):
            pass


def main() -> None:
    """以 stdio 传输运行富途 MCP 服务器。"""
    _install_hard_exit_handlers()
    server = build_server()
    try:
        server.run(transport="stdio")
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
