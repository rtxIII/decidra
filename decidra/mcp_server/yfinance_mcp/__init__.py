"""Vendored yfinance MCP 服务器（供终端 agent 使用免费的雅虎财经数据）。

来源: https://github.com/Adity-star/mcp-yfinance-server (MIT License, Copyright (c)
2025 Aditya AK)。内部导入已改为相对导入以适配 Decidra 包结构；除此之外保持原样。

提供 17 个工具：股价/公司信息、历史行情、财报、技术指标（MA/RSI/MACD/布林/技术摘要）、
自选清单、新闻、分析师评级、个股对比。基于 yfinance，免费、无需 API key。

启动: ``python -m decidra.mcp_server.yfinance_mcp``
"""
