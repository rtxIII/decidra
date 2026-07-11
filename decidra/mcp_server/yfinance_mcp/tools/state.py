from enum import Enum
import time
from typing import Optional, Any
from threading import Thread, Lock

# Financial statement types
class FinancialType(str, Enum):
    income_stmt = "income_stmt"
    quarterly_income_stmt = "quarterly_income_stmt"
    balance_sheet = "balance_sheet"
    quarterly_balance_sheet = "quarterly_balance_sheet"
    cashflow = "cashflow"
    quarterly_cashflow = "quarterly_cashflow"

# Holder types
class HolderType(str, Enum):
    major_holders = "major_holders"
    institutional_holders = "institutional_holders"
    mutualfund_holders = "mutualfund_holders"
    insider_transactions = "insider_transactions"
    insider_purchases = "insider_purchases"
    insider_roster_holders = "insider_roster_holders"


# Recommendation types
class RecommendationType(str, Enum):
    recommendations = "recommendations"
    upgrades_downgrades = "upgrades_downgrades"

class ServerState:
    """Global state manager for MCP server."""
    def __init__(self):
        self.watchlist = set()
        self.watchlist_prices = {}
        self.price_cache = {}
        self.cache_timeout = 300  # seconds
        self.update_thread: Optional[Thread] = None
        self.running = True
        self._lock = Lock()
    
    def add_to_cache(self, symbol: str, data: Any):
        """Add data to cache with timestamp"""
        with self._lock:
            self.price_cache[symbol] = {
                'data': data,
                'timestamp': time.time()
            }
    
    def get_from_cache(self, symbol: str) -> Optional[Any]:
        """Get data from cache if not expired"""
        with self._lock:
            if symbol in self.price_cache:
                cache_entry = self.price_cache[symbol]
                if time.time() - cache_entry['timestamp'] < self.cache_timeout:
                    return cache_entry['data']
                else:
                    del self.price_cache[symbol]
        return None
    
    def cleanup_cache(self):
        """Remove expired cache entries"""
        current_time = time.time()
        with self._lock:
            expired_keys = [
                key for key, value in self.price_cache.items()
                if current_time - value['timestamp'] > self.cache_timeout
            ]
            for key in expired_keys:
                del self.price_cache[key]