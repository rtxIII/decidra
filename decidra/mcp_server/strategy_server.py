"""策略告警研判 MCP 服务器（stdio）。

给终端 agent 暴露策略告警的读取与研判结论写回，实现"人工在终端触发研判"：
用户说"研判 #a1b2c3"，agent 经 strategy_alerts_list 取告警上下文，复核缠论
结构（czsc 工具）与行情/基本面（yfinance 工具）后，用 strategy_alert_enrich
落盘结论；monitor 面板回放时展示研判结果。

启动: ``python -m decidra.mcp_server.strategy_server``
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

VALID_CONCLUSIONS = ("支持", "反对", "观望")
VALID_CONFIDENCES = ("高", "中", "低")


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": str(message)}, ensure_ascii=False)


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def build_server() -> FastMCP:
    """构建策略告警 MCP 服务器并注册工具。"""
    mcp = FastMCP("strategy")

    @mcp.tool()
    def strategy_alerts_list(n: int = 10) -> str:
        """列出最近 n 条策略告警（含研判状态），供人工触发研判时获取上下文。

        每条告警含：短码 id、时间 dt、symbol（富途码）、action(BUY/SELL)、reason、
        触发 K 线 bar_dt、snapshot（收盘价/日线买卖点/周线方向/共振信号）、
        enriched 是否已研判、enrichment 已研判时的结论。

        研判流程（用户要求研判某条告警时遵循）：

        1. 用 czsc_multi_level_analysis 复核该 symbol 的多级别缠论结构与信号；
        2. 关注返回中的 data_quality_issues，数据可疑时降低置信度；
        3. 用 yfinance 工具核对近期行情/基本面是否支持告警方向；
        4. 得出结论后必须调用 strategy_alert_enrich 落盘（结论=支持/反对/观望）。

        注意 symbol 格式转换：告警用富途码（如 HK.00700），czsc/yfinance 工具
        用 yfinance 码（如 0700.HK）。
        """
        from ..strategy import alerts as alerts_mod

        try:
            recent = alerts_mod.read_recent_alerts(n, alerts_mod.ALERTS_PATH)
            enrichments = alerts_mod.load_enrichments()
            for alert in recent:
                enrichment = enrichments.get(alert.get("id") or "")
                alert["enriched"] = enrichment is not None
                if enrichment:
                    alert["enrichment"] = enrichment
            return _ok({"count": len(recent), "alerts": recent})
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def strategy_alert_enrich(
        alert_id: str, conclusion: str, summary: str, confidence: str = "中"
    ) -> str:
        """把研判结论写回策略告警（按短码 id 定位），monitor 面板将展示研判结果。

        Args:
            alert_id: 告警短码 id（strategy_alerts_list 返回的 id 字段，可带 # 前缀）。
            conclusion: 支持 / 反对 / 观望 —— 对告警方向的研判结论。
            summary: 论据摘要（1-3 句，含关键证据：结构复核结果、行情/基本面要点）。
            confidence: 置信度 高 / 中 / 低，默认 中。
        """
        from ..strategy import alerts as alerts_mod

        try:
            alert_id = alert_id.lstrip("#").strip()
            if conclusion not in VALID_CONCLUSIONS:
                return _err(f"结论必须为 {'/'.join(VALID_CONCLUSIONS)}，收到: {conclusion!r}")
            if confidence not in VALID_CONFIDENCES:
                return _err(f"置信度必须为 {'/'.join(VALID_CONFIDENCES)}，收到: {confidence!r}")
            alert = alerts_mod.find_alert(alert_id)
            if alert is None:
                return _err(f"未找到告警: {alert_id}（用 strategy_alerts_list 核对 id）")

            enrichment = {
                "conclusion": conclusion,
                "confidence": confidence,
                "summary": summary,
                "dt": datetime.now().isoformat(timespec="seconds"),
            }
            alerts_mod.save_enrichment(alert_id, enrichment)
            return _ok({
                "alert_id": alert_id,
                "symbol": alert.get("symbol"),
                "action": alert.get("action"),
                "enrichment": enrichment,
            })
        except Exception as exc:
            return _err(exc)

    return mcp


def main() -> None:
    """以 stdio 传输运行策略告警 MCP 服务器。

    ``run`` 在父进程关闭 stdio 后返回；随后 ``os._exit`` 强制退出，确保子进程被
    openharness 干净回收（与 futu/yfinance/czsc server 一致）。
    """
    import os
    try:
        build_server().run(transport="stdio")
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
