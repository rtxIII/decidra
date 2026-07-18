# -*- coding: utf-8 -*-
"""
===================================
数据源策略层 - 包初始化
===================================

本包实现策略模式管理多个数据源，实现：
1. 统一的数据获取接口
2. 自动故障切换
3. 防封禁流控策略
"""

from decidra.base.data import BaseFetcher, DataFetcherManager
from .akshare import AkshareFetcher
from .baostock import BaostockFetcher
from .tdx import TdxFetcher
from .yfinance import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'AkshareFetcher',
    'BaostockFetcher',
    'TdxFetcher',
    'YfinanceFetcher',
]