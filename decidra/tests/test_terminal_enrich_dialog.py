"""终端 /enrich 命令解析、命令提示、告警选择对话框与面板链路测试。

对话框与面板用 Textual 测试驱动真实按键交互；面板链路注入记录用 runtime、
临时目录替换告警路径（与 TestStrategyServer 相同的注入模式），无 mock。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

from decidra.monitor.terminal.console_panel import (
    HINTS_ID,
    TerminalConsolePanel,
    filter_command_hints,
)
from decidra.monitor.terminal.enrich_dialog import AlertPickDialog, parse_enrich_command


class TestParseEnrichCommand(unittest.TestCase):
    def test_not_enrich_command(self):
        self.assertIsNone(parse_enrich_command("你好"))
        self.assertIsNone(parse_enrich_command("/session"))
        self.assertIsNone(parse_enrich_command("/enrichment"), "同前缀他词不应命中")
        self.assertIsNone(parse_enrich_command("/研判"), "旧中文命令已废弃，走自然语言")

    def test_no_arg_means_picker(self):
        self.assertEqual(parse_enrich_command("/enrich"), "")
        self.assertEqual(parse_enrich_command("  /enrich  "), "")

    def test_arg_forms(self):
        self.assertEqual(parse_enrich_command("/enrich a1b2c3d4"), "a1b2c3d4")
        self.assertEqual(parse_enrich_command("/enrich #a1b2c3d4"), "a1b2c3d4")
        self.assertEqual(parse_enrich_command("/enrich#a1b2c3d4"), "a1b2c3d4")


class TestFilterCommandHints(unittest.TestCase):
    COMMANDS = [("enrich", "研判策略告警"), ("help", "Show help"), ("session", "Session info")]

    def test_non_slash_input_hidden(self):
        self.assertEqual(filter_command_hints("", self.COMMANDS), [])
        self.assertEqual(filter_command_hints("hello", self.COMMANDS), [])

    def test_bare_slash_lists_all(self):
        self.assertEqual(len(filter_command_hints("/", self.COMMANDS)), 3)

    def test_prefix_filters(self):
        self.assertEqual(filter_command_hints("/en", self.COMMANDS),
                         [("enrich", "研判策略告警")])

    def test_arg_typing_hides(self):
        self.assertEqual(filter_command_hints("/enrich ", self.COMMANDS), [],
                         "出现空格（开始输参数）后应隐藏提示")


class _DialogHarness(App):
    """承载 AlertPickDialog 的最小 App，捕获 dismiss 结果。"""

    def __init__(self, options):
        super().__init__()
        self._options = options
        self.result: object = "UNSET"

    def on_mount(self) -> None:
        self.push_screen(AlertPickDialog(self._options), self._capture)

    def _capture(self, value) -> None:
        self.result = value


class TestAlertPickDialog(unittest.IsolatedAsyncioTestCase):
    OPTIONS = [
        ("id_new", "[dim]#id_new[/] [bold green]▲ BUY[/] HK.09988  [yellow]未研判[/]"),
        ("id_old", "[dim]#id_old[/] [bold red]▼ SELL[/] HK.00700  [green]已研判·支持[/]"),
    ]

    async def test_enter_returns_highlighted_id(self):
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, "id_old")

    async def test_escape_returns_none(self):
        app = _DialogHarness(self.OPTIONS)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertIsNone(app.result)


class _RecordingRuntime:
    """记录提交行的最小 runtime（面板依赖 submit 与 list_slash_commands 协议）。"""

    def __init__(self):
        self.submitted: list[str] = []

    async def submit(self, line, *, render_event, print_system=None, clear_output=None):
        self.submitted.append(line)

    def list_slash_commands(self):
        return [("help", "Show help"), ("session", "Session info")]


class _PanelHarness(App):
    """承载 TerminalConsolePanel 的最小 App。"""

    def __init__(self, runtime):
        super().__init__()
        self._runtime = runtime

    def compose(self) -> ComposeResult:
        yield TerminalConsolePanel()

    def on_mount(self) -> None:
        panel = self.query_one(TerminalConsolePanel)
        panel.set_runtime(self._runtime)
        panel.focus_input()


class TestEnrichPanelFlow(unittest.IsolatedAsyncioTestCase):
    """/研判 从输入拦截到 prompt 提交的面板级链路。"""

    def setUp(self):
        import decidra.strategy.alerts as alerts_mod

        self.alerts_mod = alerts_mod
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_alerts = alerts_mod.ALERTS_PATH
        self._orig_enrich = alerts_mod.ENRICHMENTS_PATH
        alerts_mod.ALERTS_PATH = Path(self._tmp.name) / "alerts.jsonl"
        alerts_mod.ENRICHMENTS_PATH = Path(self._tmp.name) / "enrichments.json"

        self.alert = alerts_mod.Alert(
            dt="2026-07-13T20:36:03", symbol="HK.00700", strategy="czsc_resonance",
            action="SELL", reason="周日线中枢共振看空", bar_dt="2026-07-13T00:00:00",
            snapshot={"last_close": 457.6})
        alerts_mod.append_alerts([self.alert], alerts_mod.ALERTS_PATH)

    def tearDown(self):
        self.alerts_mod.ALERTS_PATH = self._orig_alerts
        self.alerts_mod.ENRICHMENTS_PATH = self._orig_enrich
        self._tmp.cleanup()

    async def _submit_and_wait(self, pilot, panel, runtime, line, expect_dialog):
        panel.input.value = line
        await pilot.press("enter")
        if expect_dialog:
            for _ in range(100):  # 等 worker 弹出对话框
                await pilot.pause(0.02)
                if isinstance(pilot.app.screen, AlertPickDialog):
                    break
            self.assertIsInstance(pilot.app.screen, AlertPickDialog, "应弹出选择对话框")
            await pilot.press("enter")  # 选中第一条（最新）
        for _ in range(100):  # 等 worker 完成提交
            await pilot.pause(0.02)
            if runtime.submitted:
                break

    async def test_picker_flow_submits_enrich_prompt(self):
        runtime = _RecordingRuntime()
        app = _PanelHarness(runtime)
        async with app.run_test() as pilot:
            panel = app.query_one(TerminalConsolePanel)
            await self._submit_and_wait(pilot, panel, runtime, "/enrich", expect_dialog=True)
        self.assertEqual(len(runtime.submitted), 1)
        prompt = runtime.submitted[0]
        self.assertIn(f"#{self.alert.id}", prompt)
        self.assertIn("strategy_alert_enrich", prompt)

    async def test_direct_id_skips_dialog(self):
        runtime = _RecordingRuntime()
        app = _PanelHarness(runtime)
        async with app.run_test() as pilot:
            panel = app.query_one(TerminalConsolePanel)
            await self._submit_and_wait(
                pilot, panel, runtime, f"/enrich #{self.alert.id}", expect_dialog=False)
        self.assertEqual(len(runtime.submitted), 1)
        self.assertIn(f"#{self.alert.id}", runtime.submitted[0])


class TestCommandHintsFlow(unittest.IsolatedAsyncioTestCase):
    """输入 / 时的命令提示条展示与隐藏。"""

    async def test_hints_follow_input(self):
        runtime = _RecordingRuntime()
        app = _PanelHarness(runtime)
        async with app.run_test() as pilot:
            panel = app.query_one(TerminalConsolePanel)
            hints = panel.query_one(f"#{HINTS_ID}", Static)
            self.assertFalse(hints.display, "初始应隐藏")

            panel.input.value = "/"
            await pilot.pause()
            self.assertTrue(hints.display, "输入 / 应展示命令提示")
            self.assertIsNotNone(panel.input.suggester, "拿到运行时命令后应挂内联补全")

            panel.input.value = "/enr"
            await pilot.pause()
            self.assertTrue(hints.display, "前缀匹配 /enrich 应保持展示")

            panel.input.value = "hello"
            await pilot.pause()
            self.assertFalse(hints.display, "非命令输入应隐藏提示")


if __name__ == "__main__":
    unittest.main()
