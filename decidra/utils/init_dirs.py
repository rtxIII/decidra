#!/usr/bin/env python3
"""
目录初始化工具

功能:
1. 创建 Decidra 所需的所有运行时目录
2. 可在安装后或首次运行时调用
3. 确保目录权限正确
"""

import os
from pathlib import Path
from typing import List, Tuple


def ensure_directories() -> Tuple[bool, List[str]]:
    """
    确保所有必需的目录存在

    Returns:
        (success, created_dirs): 成功标志和已创建目录列表
    """
    from .global_vars import (
        PATH,
        PATH_RUNTIME,
        PATH_CONFIG,
        PATH_DATA,
        PATH_LOG,
    )

    # 需要创建的目录列表
    directories = [
        PATH,                           # 主配置目录 ~/.decidra
        PATH_RUNTIME,                   # 运行时目录
        PATH_RUNTIME / 'config',        # 运行时配置
        PATH_DATA,                      # 数据缓存
        PATH_LOG,                       # 日志目录
    ]

    created_dirs = []

    for directory in directories:
        try:
            dir_path = Path(directory)
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created_dirs.append(str(dir_path))
        except Exception as e:
            print(f"创建目录失败: {directory}, 错误: {e}")
            return False, created_dirs

    return True, created_dirs


def verify_directories() -> Tuple[bool, List[str]]:
    """
    验证所有必需目录是否存在且可写

    Returns:
        (all_ok, missing_dirs): 验证结果和缺失目录列表
    """
    from .global_vars import (
        PATH,
        PATH_RUNTIME,
        PATH_DATA,
        PATH_LOG,
    )

    required_dirs = [
        PATH,
        PATH_RUNTIME,
        PATH_DATA,
        PATH_LOG,
    ]

    missing_dirs = []

    for directory in required_dirs:
        dir_path = Path(directory)
        if not dir_path.exists():
            missing_dirs.append(str(dir_path))
        elif not os.access(dir_path, os.W_OK):
            missing_dirs.append(f"{dir_path} (不可写)")

    return len(missing_dirs) == 0, missing_dirs


def initialize_decidra_dirs(verbose: bool = False) -> bool:
    """
    初始化 Decidra 目录结构

    Args:
        verbose: 是否输出详细信息

    Returns:
        是否成功
    """
    if verbose:
        print("初始化 Decidra 目录结构...")

    # 创建目录
    success, created_dirs = ensure_directories()

    if verbose:
        if created_dirs:
            print(f"已创建 {len(created_dirs)} 个目录:")
            for dir_path in created_dirs:
                print(f"  - {dir_path}")
        else:
            print("所有目录已存在")

    # 验证目录
    all_ok, missing_dirs = verify_directories()

    if not all_ok:
        if verbose:
            print(f"警告: {len(missing_dirs)} 个目录缺失或不可写:")
            for dir_path in missing_dirs:
                print(f"  - {dir_path}")
        return False

    if verbose:
        print("目录初始化完成")

    return True


if __name__ == '__main__':
    import sys

    # 命令行调用时显示详细信息
    success = initialize_decidra_dirs(verbose=True)
    sys.exit(0 if success else 1)
