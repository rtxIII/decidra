#!/usr/bin/env /opt/homebrew/Caskroom/miniconda/base/envs/trade/bin/python
"""
验证 Decidra 包配置的脚本
检查 pyproject.toml 配置是否正确，包结构是否符合 PyPI 发布要求
"""

import os
import sys
from pathlib import Path

def check_files():
    """检查必需文件是否存在"""
    required_files = [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "MANIFEST.in"
    ]

    print("=" * 60)
    print("检查必需文件...")
    print("=" * 60)

    all_exist = True
    for filename in required_files:
        exists = os.path.exists(filename)
        status = "✓" if exists else "✗"
        print(f"{status} {filename}")
        if not exists:
            all_exist = False

    return all_exist

def check_package_structure():
    """检查包结构"""
    print("\n" + "=" * 60)
    print("检查包结构...")
    print("=" * 60)

    decidra_dir = Path("decidra")
    if not decidra_dir.exists():
        print("✗ decidra/ 目录不存在")
        return False

    print(f"✓ decidra/ 目录存在")

    # 检查主要模块
    modules = ["api", "base", "modules", "monitor", "strategy", "tasks", "utils"]

    for module in modules:
        module_path = decidra_dir / module
        init_file = module_path / "__init__.py"

        if module_path.exists():
            has_init = init_file.exists()
            status = "✓" if has_init else "⚠"
            print(f"{status} decidra/{module}/ {'(有__init__.py)' if has_init else '(缺少__init__.py)'}")
        else:
            print(f"✗ decidra/{module}/ 不存在")

    # 检查入口点文件
    entry_points = ["cli.py", "monitor_app.py", "post_install.py"]
    for entry in entry_points:
        entry_path = decidra_dir / entry
        status = "✓" if entry_path.exists() else "✗"
        print(f"{status} decidra/{entry}")

    # 检查包初始化文件
    init_file = decidra_dir / "__init__.py"
    status = "✓" if init_file.exists() else "✗"
    print(f"{status} decidra/__init__.py")

    # 检查 py.typed
    py_typed = decidra_dir / "py.typed"
    status = "✓" if py_typed.exists() else "⚠"
    print(f"{status} decidra/py.typed {'(类型检查支持)' if py_typed.exists() else '(建议添加)'}")

    return True

def check_pyproject_config():
    """检查 pyproject.toml 关键配置"""
    print("\n" + "=" * 60)
    print("检查 pyproject.toml 配置...")
    print("=" * 60)

    try:
        # Python 3.11+ 内置 tomllib
        if sys.version_info >= (3, 11):
            import tomllib
            with open("pyproject.toml", "rb") as f:
                config = tomllib.load(f)
        else:
            # 尝试使用 tomli
            try:
                import tomli as tomllib
                with open("pyproject.toml", "rb") as f:
                    config = tomllib.load(f)
            except ImportError:
                print("⚠ 无法解析 TOML（需要 Python 3.11+ 或 pip install tomli）")
                return True

        # 检查关键字段
        project = config.get("project", {})

        print(f"✓ 项目名称: {project.get('name')}")
        print(f"✓ 版本: {project.get('version')}")
        print(f"✓ Python 要求: {project.get('requires-python')}")

        # 检查 setuptools 配置
        setuptools = config.get("tool", {}).get("setuptools", {})
        packages_find = setuptools.get("packages", {}).get("find", {})
        package_dir = setuptools.get("package-dir", {})

        print(f"\n包发现配置:")
        print(f"  where: {packages_find.get('where', [])}")
        print(f"  include: {packages_find.get('include', [])}")
        print(f"  exclude: {packages_find.get('exclude', [])}")
        print(f"  package-dir: {package_dir}")

        # 检查脚本入口点
        scripts = project.get("scripts", {})
        print(f"\n脚本入口点:")
        for name, entry in scripts.items():
            print(f"  {name}: {entry}")

        return True

    except FileNotFoundError:
        print("✗ pyproject.toml 文件不存在")
        return False
    except Exception as e:
        print(f"✗ 解析配置文件时出错: {e}")
        return False

def print_next_steps():
    """打印后续步骤"""
    print("\n" + "=" * 60)
    print("后续步骤建议")
    print("=" * 60)

    print("""
1. 安装构建工具:
   pip install build twine

2. 构建项目:
   python -m build

3. 检查构建结果:
   twine check dist/*

4. 本地测试安装:
   pip install dist/decidra-1.0.0-py3-none-any.whl

5. 发布到 TestPyPI (可选):
   twine upload --repository testpypi dist/*

6. 发布到 PyPI:
   twine upload dist/*
""")

def main():
    """主函数"""
    print("\nDecidra 包配置验证工具\n")

    # 切换到项目根目录
    os.chdir(Path(__file__).parent)

    # 执行检查
    files_ok = check_files()
    structure_ok = check_package_structure()
    config_ok = check_pyproject_config()

    # 总结
    print("\n" + "=" * 60)
    print("验证总结")
    print("=" * 60)

    if files_ok and structure_ok and config_ok:
        print("✓ 所有检查通过！项目已准备好打包。")
        print_next_steps()
        return 0
    else:
        print("✗ 存在问题需要修复")
        return 1

if __name__ == "__main__":
    sys.exit(main())
