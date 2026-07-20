"""出厂默认技能（decidra.skills）打包、加载、覆盖与信号引擎可用性测试。

覆盖计划 S1 的验收项：
  ① 每个出厂技能的 SKILL.md 随包可取且 frontmatter 含 name/description（防打包漏文件）。
  ② openharness 真实加载出厂技能目录，registry 能按名命中全部技能。
  ③ 覆盖语义：用户 workspace 同名技能覆盖出厂版（依赖 extra_skill_dirs 顺序）。
  ④ candlestick / technical-basic 的 example_signal_engine.py 可加载且
     generate(data_map) 返回 Dict[str, pd.Series]（合成数据，无网络）。

遵循项目约定：unittest、不使用 mock。②③ 依赖 openharness，缺失时跳过。

运行：``python -m unittest decidra.tests.test_bundled_skills``
"""

from __future__ import annotations

import importlib.util
import unittest
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd

# 出厂默认技能集。新增出厂技能时同步更新，本集合即“应打包清单”。
# S1 纯复制：candlestick / technical-basic / regulatory-knowledge / research-discipline / risk-analysis
# S2 适配：chanlun（接 czsc_lite MCP 工具）/ sentiment-analysis（verbatim）/ financial-statement（数据源接线）
EXPECTED_SKILLS: frozenset[str] = frozenset(
    {
        "candlestick",
        "technical-basic",
        "regulatory-knowledge",
        "research-discipline",
        "risk-analysis",
        "chanlun",
        "sentiment-analysis",
        "financial-statement",
    }
)

# 带 example_signal_engine.py 参考脚本的技能（纯 pandas，可插回测）。
SIGNAL_ENGINE_SKILLS: frozenset[str] = frozenset({"candlestick", "technical-basic"})

try:
    from openharness.skills.loader import load_skills_from_dirs
    from openharness.skills.registry import SkillRegistry

    _HAS_OPENHARNESS = True
except Exception:  # noqa: BLE001 - 环境未装 openharness 时跳过②③，不阻断①④
    _HAS_OPENHARNESS = False


def _skills_root() -> Path:
    """出厂技能包 decidra.skills 的文件系统根目录。"""
    return Path(str(files("decidra.skills")))


def _skill_md(skill: str) -> Path:
    return _skills_root() / skill / "SKILL.md"


def _frontmatter_block(text: str) -> str:
    """取 YAML frontmatter 块（首个 --- 到第二个 --- 之间），无则返回空串。"""
    if not text.startswith("---"):
        return ""
    end = text.find("---", 3)
    return text[3:end] if end != -1 else ""


def _synthetic_ohlc(rows: int = 80) -> pd.DataFrame:
    """构造合成日线 OHLCV（DatetimeIndex + 小写列），high/low 边界自洽，无网络。"""
    idx = pd.bdate_range("2024-01-01", periods=rows)
    t = np.arange(rows, dtype=float)
    close = 100.0 + 10.0 * np.sin(t / 6.0) + t * 0.05
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    volume = 1_000_000 + (t % 7) * 10_000
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _load_engine_module(skill: str):
    """按文件路径动态加载技能的 example_signal_engine.py（不经包导入）。"""
    path = _skills_root() / skill / "example_signal_engine.py"
    spec = importlib.util.spec_from_file_location(f"_bundled_{skill}_engine", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBundledSkillsPackaging(unittest.TestCase):
    """① 打包完整性 + frontmatter 校验（不依赖 openharness）。"""

    def test_expected_skills_present_with_frontmatter(self) -> None:
        for skill in sorted(EXPECTED_SKILLS):
            md = _skill_md(skill)
            self.assertTrue(md.is_file(), f"缺少出厂技能 SKILL.md: {skill}")
            text = md.read_text(encoding="utf-8")
            fm = _frontmatter_block(text)
            self.assertTrue(fm, f"{skill}/SKILL.md 缺少 YAML frontmatter")
            self.assertIn("name:", fm, f"{skill} frontmatter 缺 name")
            self.assertIn("description:", fm, f"{skill} frontmatter 缺 description")

    def test_signal_engine_scripts_present(self) -> None:
        for skill in sorted(SIGNAL_ENGINE_SKILLS):
            path = _skills_root() / skill / "example_signal_engine.py"
            self.assertTrue(path.is_file(), f"缺少信号引擎脚本: {skill}")

    def test_attribution_present(self) -> None:
        self.assertTrue(
            (_skills_root() / "ATTRIBUTION.md").is_file(),
            "缺少 ATTRIBUTION.md（MIT 合规溯源）",
        )


class TestBundledSignalEngines(unittest.TestCase):
    """④ 参考信号引擎可加载并产出信号（合成数据，无网络）。"""

    def test_generate_returns_signal_series(self) -> None:
        data = _synthetic_ohlc()
        data_map = {"TEST.001": data}
        for skill in sorted(SIGNAL_ENGINE_SKILLS):
            module = _load_engine_module(skill)
            self.assertTrue(
                hasattr(module, "SignalEngine"),
                f"{skill} 缺 SignalEngine 类",
            )
            engine = module.SignalEngine()
            result = engine.generate(data_map)
            self.assertIsInstance(result, dict, f"{skill}.generate 应返回 dict")
            self.assertIn("TEST.001", result, f"{skill} 未产出目标信号")
            series = result["TEST.001"]
            self.assertIsInstance(series, pd.Series, f"{skill} 信号应为 pd.Series")
            self.assertTrue(series.index.equals(data.index), f"{skill} 信号索引须对齐 K 线")
            self.assertTrue(set(pd.unique(series.dropna())).issubset({-1, 0, 1}))


@unittest.skipUnless(_HAS_OPENHARNESS, "未安装 openharness，跳过技能加载/覆盖测试")
class TestBundledSkillsLoading(unittest.TestCase):
    """②③ openharness 真实加载与覆盖语义。"""

    def test_openharness_loads_all_bundled_skills(self) -> None:
        skills = load_skills_from_dirs([str(_skills_root())], source="bundled")
        names = {s.name for s in skills}
        missing = EXPECTED_SKILLS - names
        self.assertFalse(missing, f"openharness 未加载到出厂技能: {sorted(missing)}")

    def test_workspace_skill_overrides_bundled(self) -> None:
        import tempfile

        override_desc = "WORKSPACE-OVERRIDE-MARKER"
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            skill_dir = ws / "candlestick"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: candlestick\ndescription: {override_desc}\n---\n覆盖版\n",
                encoding="utf-8",
            )
            # 复刻 runtime_bridge 的顺序：出厂默认在前、workspace 在后；后注册覆盖前者。
            registry = SkillRegistry()
            for skill in load_skills_from_dirs(
                [str(_skills_root()), str(ws)], source="bundled"
            ):
                registry.register(skill)
            resolved = registry.get("candlestick")
            self.assertIsNotNone(resolved)
            self.assertEqual(
                resolved.description,
                override_desc,
                "用户 workspace 同名技能未覆盖出厂默认",
            )


if __name__ == "__main__":
    unittest.main()
