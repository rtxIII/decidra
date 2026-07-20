# 出厂技能来源与许可

本目录的部分技能移植自开源项目 **HKUDS/Vibe-Trading**（<https://github.com/HKUDS/Vibe-Trading>，MIT License）的 `agent/src/skills/`。

依据 MIT 许可，保留原始版权与授权声明。移植方式如下：

| 技能 | 来源 | 移植方式 |
| --- | --- | --- |
| candlestick | Vibe-Trading `skills/candlestick` | 原样移植（SKILL.md + 纯 pandas 信号引擎） |
| technical-basic | Vibe-Trading `skills/technical-basic` | 原样移植（SKILL.md + 纯 pandas 信号引擎） |
| regulatory-knowledge | Vibe-Trading `skills/regulatory-knowledge` | 原样移植（纯知识） |
| research-discipline | Vibe-Trading `skills/research-discipline` | 原样移植（纯知识） |
| risk-analysis | Vibe-Trading `skills/risk-analysis` | 原样移植（纯知识） |
| sentiment-analysis | Vibe-Trading `skills/sentiment-analysis` | 原样移植（纯知识） |
| chanlun references | Vibe-Trading `skills/chanlun/references` | 原样移植（缠论核心概念/买卖点知识） |
| chanlun SKILL.md | Vibe-Trading `skills/chanlun` 骨架 | 改写：用法段接线到 Decidra czsc_lite MCP 工具（`czsc_chan_analysis` / `czsc_multi_level_analysis` / `czsc_list_signals`）与策略研判（`strategy_alerts_list` / `strategy_alert_enrich`），移除完整 czsc 库依赖 |
| financial-statement | Vibe-Trading `skills/financial-statement` | 移植 + 数据源接线（`extra_fields` 改为 Decidra 内置 akshare/tushare/baostock/yfinance） |

上游 MIT 许可全文见 Vibe-Trading 仓库 `LICENSE`。
