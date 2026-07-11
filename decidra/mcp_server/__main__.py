"""富途 MCP 服务器启动入口。

用法: ``python -m decidra.mcp_server``（stdio 传输，供 MCP 客户端以子进程方式连接）。
"""

from .futu_server import build_server


def main() -> None:
    """以 stdio 传输运行富途 MCP 服务器。"""
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
