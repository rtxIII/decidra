"""监控界面股票名称展示与策略打标行为测试。"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from decidra.base.monitor import MarketStatus, StockData
from decidra.monitor.manager.ui import STRATEGY_MARK_PREFIX, UIManager
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


class TestMonitorStrategyMark(unittest.IsolatedAsyncioTestCase):
    """策略 watchlist 股票在监控列表中的打标行为。"""

    STRATEGY_STOCK = "HK.00700"
    NORMAL_STOCK = "HK.09988"

    @staticmethod
    def _write_strategy_config(directory: str, watchlist: list) -> Path:
        config_path = Path(directory) / "config.json"
        config_path.write_text(
            json.dumps({"watchlist": watchlist}, ensure_ascii=False),
            encoding="utf-8",
        )
        return config_path

    def test_load_strategy_watchlist_from_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_strategy_config(
                tmp_dir, [self.STRATEGY_STOCK, "US.AAPL", "", 123]
            )
            ui_manager = UIManager(SimpleNamespace(), None)
            ui_manager.strategy_config_path = config_path

            watchlist = ui_manager._load_strategy_watchlist()

            self.assertEqual(watchlist, {self.STRATEGY_STOCK, "US.AAPL"})

    def test_load_strategy_watchlist_failure_returns_empty(self):
        ui_manager = UIManager(SimpleNamespace(), None)
        ui_manager.strategy_config_path = Path("/nonexistent_dir_for_test/config.json")

        self.assertEqual(ui_manager._load_strategy_watchlist(), set())

    async def test_load_default_stocks_marks_strategy_stocks_aligned(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_strategy_config(tmp_dir, [self.STRATEGY_STOCK])
            app_core = SimpleNamespace(
                monitored_stocks=[self.STRATEGY_STOCK, self.NORMAL_STOCK],
                current_stock_cursor=0,
                active_table="stock",
            )
            app = _StockTablesHarness()
            ui_manager = UIManager(app_core, app)
            ui_manager.strategy_config_path = config_path

            async with app.run_test() as pilot:
                ui_manager.stock_table = app.query_one("#stock_table", DataTable)
                await ui_manager.load_default_stocks()
                await pilot.pause()

                marked_cell = ui_manager.stock_table.get_cell(
                    self.STRATEGY_STOCK, "code"
                )
                unmarked_cell = ui_manager.stock_table.get_cell(
                    self.NORMAL_STOCK, "code"
                )

                self.assertTrue(marked_cell.startswith(STRATEGY_MARK_PREFIX))
                self.assertIn(self.STRATEGY_STOCK, marked_cell)
                self.assertNotIn("▶", unmarked_cell)

                # 对齐：去除 markup 后前缀等宽，代码从同一列开始
                marked_plain = Text.from_markup(marked_cell).plain
                unmarked_plain = Text.from_markup(unmarked_cell).plain
                self.assertEqual(cell_len(marked_plain[0]), cell_len(unmarked_plain[0]))
                self.assertEqual(marked_plain[1:], self.STRATEGY_STOCK)
                self.assertEqual(unmarked_plain[1:], self.NORMAL_STOCK)

    async def test_add_stock_to_table_uses_cached_watchlist(self):
        app = _StockTablesHarness()
        ui_manager = UIManager(SimpleNamespace(), app)
        ui_manager.strategy_watchlist = {"US.AAPL"}

        async with app.run_test() as pilot:
            ui_manager.stock_table = app.query_one("#stock_table", DataTable)
            await ui_manager.add_stock_to_table("US.AAPL")
            await ui_manager.add_stock_to_table("US.MSFT")
            await pilot.pause()

            marked_cell = ui_manager.stock_table.get_cell("US.AAPL", "code")
            unmarked_cell = ui_manager.stock_table.get_cell("US.MSFT", "code")

            self.assertTrue(marked_cell.startswith(STRATEGY_MARK_PREFIX))
            self.assertEqual(Text.from_markup(unmarked_cell).plain, " US.MSFT")


if __name__ == "__main__":
    unittest.main()
