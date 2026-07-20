# 导入其他模块

from .futu_market import FutuMarket

#对应https://openapi.futunn.com/futu-api-doc/quote/overview.html
"""
富途API模块
提供统一的富途OpenAPI封装和基础功能
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from ..utils import logger
from ..utils.global_vars import *

# 使用新的API封装
from ..api.futu import create_client
from ..base.futu_class import FutuException


__all__ = [
    'FutuMarket',
]


