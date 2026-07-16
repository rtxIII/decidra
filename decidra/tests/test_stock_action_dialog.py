"""股票操作菜单对话框与策略 watchlist 更新行为测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

from decidra.monitor.manager.ui import STRATEGY_MARK_PREFIX, UIManager
from decidra.monitor.monitor_layout import STOCK_COLUMNS, MonitorLayout
from decidra.monitor.widgets.stock_action_dialog import (
    ACTION_ANALYSIS,
    ACTION_BUY,
    ACTION_DELETE,
    ACTION_SELL,
    ACTION_STRATEGY_ADD,
    ACTION_STRATEGY_REMOVE,
    StockActionDialog,
    build_stock_menu_options,
)
from decidra.strategy.config import load_config, update_watchlist

STOCK_CODE = "HK.00700"


class _KeyDispatchHarness(App):
    """真实 MonitorLayout + 股票表持焦，验证按键分发到 action_stock_menu。

    回车路径：DataTable 自带 enter=select_cursor 绑定，表格持真实焦点时会先于
    MonitorLayout 的全局绑定消费回车（须 priority=True 才能分流）。
    空格路径：space 绑定在 App 层（对齐 monitor_app），DataTable 不消费空格，
    经 select_group 按 active_table 分流。
    """

    BINDINGS = [Binding("space", "select_group", "选择分组")]

    def __init__(self):
        super().__init__()
        self.app_core = SimpleNamespace(
            active_table="stock",
            current_stock_cursor=0,
            current_stock_code=None,
            monitored_stocks=["HK.00700", "HK.09988", "HK.06082"],
        )
        # EventHandler 经 app_core.app 取 ui_manager（无则降级）
        self.app_core.app = self
        self.stock_menu_calls = 0
        self.show_splash = False
        self.managers_initialized = True

    def compose(self) -> ComposeResult:
        yield MonitorLayout(id="monitor_layout")

    def _handler(self):
        from decidra.monitor.main.event_handler import EventHandler
        if not hasattr(self, "_event_handler"):
            self._event_handler = EventHandler(self.app_core, self)
        return self._event_handler

    async def action_stock_menu(self) -> None:
        self.stock_menu_calls += 1

    async def action_select_group(self) -> None:
        # 与 monitor_app 相同的转发路径，落到真实 EventHandler 的空格分流
        await self._handler().action_select_group()

    async def on_data_table_row_highlighted(self, event) -> None:
        # 与 monitor_app 相同的转发路径，落到真实 EventHandler 的同步逻辑
        await self._handler().on_data_table_row_highlighted(event)


class TestKeyDispatch(unittest.IsolatedAsyncioTestCase):
    async def _make_focused_table(self, app, pilot, rows=1):
        stock_table = app.query_one("#stock_table", DataTable)
        for code in app.app_core.monitored_stocks[:rows]:
            stock_table.add_row(code, code, "0", "0", "0", "-", key=code)
        stock_table.focus()
        await pilot.pause()
        return stock_table

    async def test_space_on_focused_stock_table_opens_menu(self):
        """空格是弹菜单的主路径：经真实 EventHandler 的 select_group 分流，
        最终屏幕栈顶必须出现 StockActionDialog。"""
        app = _KeyDispatchHarness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._make_focused_table(app, pilot)

            await pilot.press("space")
            await pilot.pause()

            self.assertIsInstance(
                app.screen, StockActionDialog,
                "股票表激活时空格必须弹出操作菜单对话框",
            )
            await pilot.press("escape")
            await pilot.pause()

    async def test_opening_space_does_not_instantly_confirm(self):
        """唤出菜单的那次空格不得连带触发菜单内的空格确认（菜单须保持打开）。"""
        app = _KeyDispatchHarness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._make_focused_table(app, pilot)

            await pilot.press("space")
            await pilot.pause()

            self.assertIsInstance(
                app.screen, StockActionDialog,
                "单次空格后菜单应保持打开，不得被同一次按键立即确认关闭",
            )
            await pilot.press("escape")
            await pilot.pause()

    async def test_enter_on_focused_stock_table_opens_menu(self):
        app = _KeyDispatchHarness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._make_focused_table(app, pilot)

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(
                app.stock_menu_calls, 1,
                "股票表持真实焦点时按回车必须触发操作菜单（须 priority 绑定，"
                "否则被 DataTable 自带 enter=select_cursor 消费）",
            )

    async def test_arrow_keys_sync_cursor_before_menu(self):
        """表格持焦时方向键移动由 DataTable 消费，app_core 光标须经
        RowHighlighted 事件同步——否则菜单操作的是旧光标位置的股票。"""
        app = _KeyDispatchHarness()
        async with app.run_test() as pilot:
            await pilot.pause()
            stock_table = await self._make_focused_table(app, pilot, rows=3)

            await pilot.press("down")
            await pilot.press("down")
            await pilot.pause()

            self.assertEqual(stock_table.cursor_row, 2, "表格视觉光标在第 3 行")
            self.assertEqual(
                app.app_core.current_stock_cursor, 2,
                "app_core 光标必须与表格视觉光标同步（菜单按它取股票）",
            )
            self.assertEqual(app.app_core.current_stock_code, "HK.06082")


class TestBuildStockMenuOptions(unittest.TestCase):
    def test_without_position_offers_buy(self):
        options = build_stock_menu_options(
            STOCK_CODE,
            in_strategy_watchlist=False,
            has_position=False,
        )
        self.assertEqual(
            [action_id for action_id, _ in options],
            [ACTION_ANALYSIS, ACTION_BUY, ACTION_DELETE, ACTION_STRATEGY_ADD],
        )

    def test_with_position_offers_sell(self):
        options = build_stock_menu_options(
            STOCK_CODE,
            in_strategy_watchlist=True,
            has_position=True,
        )
        self.assertEqual(
            [action_id for action_id, _ in options],
            [ACTION_ANALYSIS, ACTION_SELL, ACTION_DELETE, ACTION_STRATEGY_REMOVE],
        )
        self.assertIn("卖出", options[1][1])
        self.assertIn("移出", options[3][1])


class _StockMenuActionHarness:
    """捕获股票菜单及下单对话框调用的最小应用。"""

    def __init__(self, selected_action):
        self.selected_action = selected_action
        self.worker = None
        self.dialog = None
        self.ui_manager = SimpleNamespace(
            strategy_watchlist=set(),
            info_panel=None,
            _get_stock_display_name=lambda stock_code, fallback: fallback,
        )

    def run_worker(self, worker, exclusive=False):
        self.worker = worker()

    async def push_screen_wait(self, dialog):
        self.dialog = dialog
        return self.selected_action


class TestStockMenuTradeRouting(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _make_handler(selected_action, positions):
        from decidra.monitor.main.event_handler import EventHandler

        app = _StockMenuActionHarness(selected_action)
        app_core = SimpleNamespace(
            app=app,
            active_table="stock",
            current_stock_cursor=0,
            current_position_cursor=0,
            monitored_stocks=[STOCK_CODE],
            position_data=positions,
            stock_data={STOCK_CODE: SimpleNamespace(current_price=350.0)},
            stock_basicinfo_cache={STOCK_CODE: {"lot_size": 100}},
        )
        return EventHandler(app_core, app), app

    async def _run_menu(self, selected_action, positions):
        handler, app = self._make_handler(selected_action, positions)
        await handler.action_stock_menu()
        self.assertIsNotNone(app.worker)
        await app.worker
        return app

    async def test_zero_quantity_position_offers_buy(self):
        app = await self._run_menu(
            None,
            [{"stock_code": STOCK_CODE, "qty": 0, "can_sell_qty": 0}],
        )

        self.assertEqual(app.dialog.options[1][0], ACTION_BUY)

    async def test_invalid_quantity_position_offers_buy(self):
        app = await self._run_menu(
            None,
            [{"stock_code": STOCK_CODE, "qty": "invalid", "can_sell_qty": 0}],
        )

        self.assertEqual(app.dialog.options[1][0], ACTION_BUY)

    async def test_buy_targets_menu_stock(self):
        order_dialog = AsyncMock(return_value=None)

        with patch(
            "decidra.monitor.widgets.order_dialog.show_place_order_dialog",
            order_dialog,
        ):
            await self._run_menu(ACTION_BUY, [])

        default_values = order_dialog.await_args.kwargs["default_values"]
        self.assertEqual(default_values["code"], STOCK_CODE)
        self.assertEqual(default_values["qty"], 100)
        self.assertEqual(default_values["trd_side"], "BUY")

    async def test_unsellable_position_offers_sell_without_order_dialog(self):
        positions = [
            {
                "stock_code": STOCK_CODE,
                "stock_name": "腾讯控股",
                "qty": 200,
                "can_sell_qty": 0,
                "nominal_price": 350.0,
            }
        ]
        order_dialog = AsyncMock(return_value=None)

        with patch(
            "decidra.monitor.widgets.order_dialog.show_place_order_dialog",
            order_dialog,
        ):
            app = await self._run_menu(ACTION_SELL, positions)

        self.assertEqual(app.dialog.options[1][0], ACTION_SELL)
        order_dialog.assert_not_awaited()

    async def test_sell_targets_menu_stock_instead_of_position_cursor(self):
        positions = [
            {
                "stock_code": "HK.09988",
                "stock_name": "阿里巴巴-W",
                "qty": 100,
                "can_sell_qty": 100,
                "nominal_price": 120.0,
            },
            {
                "stock_code": STOCK_CODE,
                "stock_name": "腾讯控股",
                "qty": 200,
                "can_sell_qty": 200,
                "nominal_price": 350.0,
            },
        ]
        order_dialog = AsyncMock(return_value=None)

        with patch(
            "decidra.monitor.widgets.order_dialog.show_place_order_dialog",
            order_dialog,
        ):
            app = await self._run_menu(ACTION_SELL, positions)

        self.assertEqual(app.dialog.options[1][0], ACTION_SELL)
        default_values = order_dialog.await_args.kwargs["default_values"]
        self.assertEqual(default_values["code"], STOCK_CODE)
        self.assertEqual(default_values["qty"], 200)
        self.assertEqual(default_values["trd_side"], "SELL")


class _DialogHarness(App):
    """承载 StockActionDialog 的最小 App，捕获 dismiss 结果。"""

    def __init__(self, options):
        super().__init__()
        self._options = options
        self.result: object = "UNSET"

    def on_mount(self) -> None:
        self.push_screen(
            StockActionDialog(STOCK_CODE, "腾讯控股", self._options), self._capture
        )

    def _capture(self, value) -> None:
        self.result = value


class TestStockActionDialog(unittest.IsolatedAsyncioTestCase):
    OPTIONS = build_stock_menu_options(
        STOCK_CODE,
        in_strategy_watchlist=False,
        has_position=False,
    )

    async def test_enter_returns_highlighted_action(self):
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, ACTION_STRATEGY_ADD)

    async def test_escape_returns_none(self):
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertIsNone(app.result)

    async def test_space_confirms_highlighted_action(self):
        """空格与回车等效：确认当前高亮项。"""
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("space")
            await pilot.pause()
        self.assertEqual(app.result, ACTION_BUY)

    async def test_ws_keys_move_highlight(self):
        """w/s 与 ↑↓ 等效（主界面键位习惯延续进菜单）。"""
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.press("s")
            await pilot.press("s")
            await pilot.press("w")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, ACTION_DELETE, "s,s,s,w 后高亮应停在第三项")


class TestUpdateWatchlist(unittest.TestCase):
    def test_add_remove_roundtrip_persists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"watchlist": ["US.AAPL"], "kline_days": 365}),
                encoding="utf-8",
            )

            watchlist = update_watchlist(STOCK_CODE, add=True, path=config_path)
            self.assertEqual(watchlist, ["US.AAPL", STOCK_CODE])
            # 幂等：重复加入不产生重复项
            watchlist = update_watchlist(STOCK_CODE, add=True, path=config_path)
            self.assertEqual(watchlist.count(STOCK_CODE), 1)
            # 落盘且不丢其他配置键
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn(STOCK_CODE, persisted["watchlist"])
            self.assertEqual(persisted["kline_days"], 365)

            watchlist = update_watchlist(STOCK_CODE, add=False, path=config_path)
            self.assertNotIn(STOCK_CODE, watchlist)
            self.assertNotIn(
                STOCK_CODE,
                load_config(config_path)["watchlist"],
            )

    def test_corrupt_config_rejected_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{broken json!!", encoding="utf-8")

            with self.assertRaises(ValueError):
                update_watchlist(STOCK_CODE, add=True, path=config_path)
            self.assertEqual(
                config_path.read_text(encoding="utf-8"), "{broken json!!",
                "损坏的配置文件必须原样保留供人工修复，不得被默认值覆写",
            )

    def test_non_list_watchlist_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            original = json.dumps({"watchlist": {"HK.00700": True}})
            config_path.write_text(original, encoding="utf-8")

            with self.assertRaises(ValueError):
                update_watchlist(STOCK_CODE, add=True, path=config_path)
            self.assertEqual(
                config_path.read_text(encoding="utf-8"), original,
                "watchlist 非列表时应拒写并原样保留，不得静默替换为新列表",
            )

    def test_sparse_config_stays_sparse(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"watchlist": []}), encoding="utf-8")

            update_watchlist(STOCK_CODE, add=True, path=config_path)

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(persisted.keys()), {"watchlist"},
                "只应写回 watchlist 键，默认键不得物化进用户文件",
            )

    def test_blank_entries_filtered_on_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"watchlist": ["", "  ", 123, STOCK_CODE]}),
                encoding="utf-8",
            )

            watchlist = update_watchlist("US.AAPL", add=True, path=config_path)

            self.assertEqual(watchlist, [STOCK_CODE, "US.AAPL"])


class _StockTableHarness(App):
    def compose(self) -> ComposeResult:
        stock_table = DataTable(id="stock_table")
        for column_key, column_data in STOCK_COLUMNS.items():
            stock_table.add_column(column_data["label"], key=column_key)
        yield stock_table


class TestApplyStrategyWatchlist(unittest.IsolatedAsyncioTestCase):
    async def test_apply_marks_and_unmarks_code_cells(self):
        app = _StockTableHarness()
        app_core = SimpleNamespace(monitored_stocks=[STOCK_CODE, "US.MSFT"])
        ui_manager = UIManager(app_core, app)

        async with app.run_test() as pilot:
            ui_manager.stock_table = app.query_one("#stock_table", DataTable)
            await ui_manager.add_stock_to_table(STOCK_CODE)
            await ui_manager.add_stock_to_table("US.MSFT")
            await pilot.pause()

            await ui_manager.apply_strategy_watchlist({STOCK_CODE})
            marked_cell = ui_manager.stock_table.get_cell(STOCK_CODE, "code")
            self.assertTrue(marked_cell.startswith(STRATEGY_MARK_PREFIX))
            self.assertIn(STOCK_CODE, ui_manager.strategy_watchlist)

            await ui_manager.apply_strategy_watchlist(set())
            unmarked_cell = ui_manager.stock_table.get_cell(STOCK_CODE, "code")
            self.assertEqual(Text.from_markup(unmarked_cell).plain, f" {STOCK_CODE}")
            self.assertNotIn(STOCK_CODE, ui_manager.strategy_watchlist)
            self.assertEqual(
                Text.from_markup(
                    ui_manager.stock_table.get_cell("US.MSFT", "code")
                ).plain,
                " US.MSFT",
            )


if __name__ == "__main__":
    unittest.main()
