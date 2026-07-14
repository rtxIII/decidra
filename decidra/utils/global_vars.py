
import configparser
import time
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

# 路径常量
HOME = Path.home()
DEV_PATH = Path(__file__).parent.parent
DECIDRA_PATH = HOME / '.decidra'

# 用户目录优先：始终使用 ~/.decidra 作为配置目录
# 只有在明确设置 DECIDRA_DEV_MODE=1 时才使用开发目录
import os
if os.environ.get('DECIDRA_DEV_MODE') == '1':
    PATH = DEV_PATH
else:
    PATH = DECIDRA_PATH

PATH_RUNTIME = PATH / '.runtime'
PATH_CONFIG = PATH
PATH_DATA = PATH_RUNTIME / 'data'
PATH_DATABASE = PATH_RUNTIME / 'database'  # Obsoleted
PATH_LOG = PATH_RUNTIME / 'log'

PATH_FILTERS = PATH / 'filters'
PATH_STRATEGIES = PATH / 'strategies'
PATH_FILTER_REPORT = PATH / 'stock_filter_report'

# ============================================================================
# OpenHarness 集成与策略模块路径（统一定义，勿在各模块重复硬编码）
# 始终位于用户目录 ~/.decidra，不随 DECIDRA_DEV_MODE 切换：
# openharness 配置/凭证与策略运行时状态跨开发环境共享。
# ============================================================================
PATH_OPENHARNESS = DECIDRA_PATH / 'openharness'
PATH_OPENHARNESS_DATA = PATH_OPENHARNESS / 'data'
PATH_OPENHARNESS_SETTINGS = PATH_OPENHARNESS / 'settings.json'
PATH_OHMO_WORKSPACE = DECIDRA_PATH / 'ohmo'
PATH_STRATEGY_CONFIG = DECIDRA_PATH / 'strategy'
PATH_STRATEGY_RUNTIME = DECIDRA_PATH / '.runtime' / 'strategy'

# 常量定义
DATETIME_FORMAT_DW = '%Y-%m-%d'
DATETIME_FORMAT_M = ''
ORDER_RETRY_MAX = 3

# ============================================================================
# 统一配置管理入口
# ============================================================================
# 所有模块必须通过此处获取配置，确保全局唯一的配置管理器实例

# 全局配置管理器实例（延迟初始化）
_config_manager = None


def get_config_manager():
    """
    获取全局唯一的配置管理器实例

    Returns:
        ConfigManager: 配置管理器单例
    """
    global _config_manager
    if _config_manager is None:
        from .config_manager import ConfigManager
        _config_manager = ConfigManager(config_dir=PATH_CONFIG)
    return _config_manager


def get_config(section: str, key=None, default=None):
    """
    获取配置值的便捷函数

    Args:
        section: 配置节名称
        key: 配置项键名（可选）
        default: 默认值（可选）

    Returns:
        配置值或默认值
    """
    return get_config_manager().get_config(section, key, default)


def reload_config():
    """重新加载配置"""
    global _config_manager
    if _config_manager is not None:
        _config_manager.reload_config()
    else:
        get_config_manager()


# 向后兼容的配置代理对象
class CompatibilityConfigProxy:
    """向后兼容的配置代理对象，模拟ConfigParser接口"""

    @property
    def _manager(self):
        """延迟获取配置管理器"""
        return get_config_manager()

    def __getitem__(self, section):
        """支持 config[section] 语法"""
        return self._manager.get_config(section, default={})

    def get(self, section, key=None, fallback=None):
        """支持 config.get() 方法"""
        return self._manager.get_config(section, key, fallback)

    def sections(self):
        """获取所有配置节名称"""
        return list(self._manager._config_data.keys())

    def has_section(self, section):
        """检查配置节是否存在"""
        return section in self._manager._config_data

    def items(self, section):
        """获取配置节的所有项"""
        section_data = self._manager.get_config(section, default={})
        return section_data.items() if isinstance(section_data, dict) else []


# 创建兼容性配置对象（向后兼容旧代码）
config = CompatibilityConfigProxy()


# ============================================================================
# 统一日志管理入口
# ============================================================================
# 所有模块必须通过此处获取logger，确保统一的日志配置

def get_logger(logger_name, log_level=None):
    """
    获取logger实例的统一入口

    这个函数负责：
    1. 获取应用配置
    2. 将配置传递给logger实现
    3. 返回配置好的logger实例

    Args:
        logger_name: logger名称
        log_level: 日志等级，如果为None则使用配置中的等级

    Returns:
        ColorLogger实例
    """
    from .logger import get_logger as _get_logger

    # 获取应用配置并传递给logger
    try:
        app_config = get_config_manager().get_application_config()
    except Exception:
        app_config = None

    return _get_logger(logger_name, log_level, app_config, PATH)

