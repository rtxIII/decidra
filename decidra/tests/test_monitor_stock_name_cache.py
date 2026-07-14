"""股票名称缓存生命周期行为测试。"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from decidra.base.monitor import ConnectionStatus
from decidra.monitor.main import data as data_module
from decidra.monitor.main.data import (
    BASICINFO_CACHE_FILE,
    CACHE_EXPIRY_HOURS,
    DataManager,
)


STOCK_CODE = "HK.01860"
API_STOCK_NAME = "汇量科技"
STALE_CACHED_STOCK_NAME = "MOBVISTA"


class _BasicInfoMarket:
    def get_stock_basicinfo_multi_types(self, market, stock_types):
        return [
            SimpleNamespace(
                code=STOCK_CODE,
                name=API_STOCK_NAME,
                lot_size=2000,
                stock_type="STOCK",
                main_contract=False,
                stock_child_type="",
                listing_date=None,
                delisting_date=None,
            )
        ]


def _write_expired_cache_file(cache_directory: Path) -> Path:
    cached_basicinfo = {
        "timestamp": "2026-01-19T09:49:18",
        "cache_expiry_hours": CACHE_EXPIRY_HOURS,
        "data": {
            STOCK_CODE: {
                "code": STOCK_CODE,
                "name": STALE_CACHED_STOCK_NAME,
                "lot_size": 1000,
                "stock_type": "STOCK",
            }
        },
    }
    cache_file_path = cache_directory / BASICINFO_CACHE_FILE
    cache_file_path.write_text(
        json.dumps(cached_basicinfo, ensure_ascii=False),
        encoding="utf-8",
    )
    expired_timestamp = time.time() - ((CACHE_EXPIRY_HOURS + 1) * 3600)
    os.utime(cache_file_path, (expired_timestamp, expired_timestamp))
    return cache_file_path


class TestMonitorStockNameCache(unittest.IsolatedAsyncioTestCase):
    async def test_expired_cache_refresh_overwrites_stale_name_with_api_name(self):
        app_core = SimpleNamespace(
            monitored_stocks=[STOCK_CODE],
            connection_status=ConnectionStatus.CONNECTED,
            stock_basicinfo_cache={},
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_directory = Path(temporary_directory)
            cache_file_path = _write_expired_cache_file(cache_directory)

            with patch.object(data_module, "PATH_DATA", cache_directory):
                data_manager = DataManager(app_core, _BasicInfoMarket())
                await data_manager.load_stock_basicinfo()

            persisted_basicinfo = json.loads(
                cache_file_path.read_text(encoding="utf-8")
            )["data"][STOCK_CODE]

        self.assertEqual(
            app_core.stock_basicinfo_cache[STOCK_CODE]["name"],
            API_STOCK_NAME,
        )
        self.assertEqual(
            app_core.stock_basicinfo_cache[STOCK_CODE]["lot_size"],
            2000,
        )
        self.assertEqual(persisted_basicinfo["name"], API_STOCK_NAME)

    async def test_expired_cache_names_available_when_disconnected(self):
        app_core = SimpleNamespace(
            monitored_stocks=[STOCK_CODE],
            connection_status=ConnectionStatus.DISCONNECTED,
            stock_basicinfo_cache={},
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_directory = Path(temporary_directory)
            _write_expired_cache_file(cache_directory)

            with patch.object(data_module, "PATH_DATA", cache_directory):
                data_manager = DataManager(app_core, _BasicInfoMarket())
                await data_manager.load_stock_basicinfo()

        self.assertEqual(
            app_core.stock_basicinfo_cache[STOCK_CODE]["name"],
            STALE_CACHED_STOCK_NAME,
        )


if __name__ == "__main__":
    unittest.main()
