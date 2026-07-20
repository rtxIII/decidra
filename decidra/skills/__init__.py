"""Decidra 出厂默认技能（bundled skills）。

本包是随 Decidra 发布的默认 Agent Skills 家目录，供 monitor 智能终端的
openharness 运行时通过 ``extra_skill_dirs`` 加载（见
``decidra.monitor.terminal.runtime_bridge._bundled_skills_dir``）。

每个子目录为一个技能：``<技能名>/SKILL.md``（YAML frontmatter 含 name/description）
加可选的 ``references/`` 知识文件与 ``example_signal_engine.py`` 参考脚本。子目录本身
不是 Python 包，其文件经 ``pyproject.toml`` 的 ``[tool.setuptools.package-data]``
递归 glob 打进 wheel。

技能加载优先级（后注册覆盖前者）：
``openharness 内置 < Decidra 出厂默认(本包) < 用户 workspace``——用户可在其 ohmo
workspace 的 ``skills/`` 目录放同名技能覆盖出厂版。

出厂技能来源与许可见 ``ATTRIBUTION.md``。
"""
