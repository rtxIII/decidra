"""监控界面股票名称展示行为测试。"""

import unittest
from datetime import datetime
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from decidra.base.monitor import MarketStatus, StockData
from decidra.monitor.manager.ui import UIManager
from decidra.monitor.monitor_layout import STOCK_COLUMNS


STOCK_CODE = "HK.01860"
ENGLISH_STOCK_NAME = "MOBVISTA"
CHINESE_STOCK_NAME = "汇量科技"


class _StockTablesHarness(App):
    def compose(self) -> ComposeResult:
        stock_table = DataTable(id="stock_table")
        for column_key, column_data in STOCK_COLUMNS.items():
            stock_table.add_column(column_data["label"], key=column_key)
        stock_table.add_row(
            STOCK_CODE,
            ENGLISH_STOCK_NAME,
            "0.00",
            "0.00%",
            "0",
            "未更新",
            key=STOCK_CODE,
        )
        yield stock_table

        position_table = DataTable(id="position_table")
        position_table.add_columns(
            "股票代码",
            "股票名称",
            "持仓数量",
            "可卖数量",
            "成本价",
            "当前价",
            "盈亏",
            "盈亏比例",
        )
        yield position_table


class TestMonitorStockNames(unittest.IsolatedAsyncioTestCase):
    async def test_stock_and_position_tables_prefer_cached_name(self):
        stock_data = StockData(
            code=STOCK_CODE,
            name=ENGLISH_STOCK_NAME,
            current_price=128.5,
            open_price=127.0,
            prev_close=126.92,
            change_rate=1.25,
            change_amount=1.58,
            volume=1000,
            turnover=128500.0,
            high_price=129.0,
            low_price=126.5,
            update_time=datetime.now(),
            market_status=MarketStatus.OPEN,
        )
        app_core = SimpleNamespace(
            monitored_stocks=[STOCK_CODE],
            stock_data={STOCK_CODE: stock_data},
            stock_basicinfo_cache={
                STOCK_CODE: {"code": STOCK_CODE, "name": CHINESE_STOCK_NAME}
            },
            position_data=[
                {
                    "stock_code": STOCK_CODE,
                    "stock_name": ENGLISH_STOCK_NAME,
                    "qty": 100,
                    "can_sell_qty": 100,
                    "cost_price": 120.0,
                    "nominal_price": 128.5,
                    "pl_val": 850.0,
                    "pl_ratio": 7.08,
                }
            ],
        )
        app = _StockTablesHarness()
        ui_manager = UIManager(app_core, app)
        ui_manager.last_cell_values = {
            f"{STOCK_CODE}:price": "128.50",
            f"{STOCK_CODE}:change": "1.25%",
            f"{STOCK_CODE}:volume": "1,000",
        }

        async with app.run_test() as pilot:
            ui_manager.stock_table = app.query_one("#stock_table", DataTable)
            ui_manager.position_table = app.query_one("#position_table", DataTable)

            await ui_manager.update_stock_table()
            await ui_manager.update_position_table()
            await pilot.pause()

            self.assertEqual(
                ui_manager.stock_table.get_cell(STOCK_CODE, "name"),
                CHINESE_STOCK_NAME,
            )
            self.assertEqual(
                ui_manager.position_table.get_row_at(0)[1],
                CHINESE_STOCK_NAME,
            )


if __name__ == "__main__":
    unittest.main()
