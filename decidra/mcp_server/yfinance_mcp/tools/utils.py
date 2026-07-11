import yfinance as yf
import logging
from datetime import datetime
from typing import Dict, Any



# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yfinance-mcp-server")

# Utility Functions
def fetch_ticker(symbol: str) -> yf.Ticker:
    """Helper to safely fetch a yfinance Ticker"""
    return yf.Ticker(symbol.upper())

def safe_get_price(ticker: yf.Ticker) -> float:
    """Safely retrieve current stock price"""
    try:
        # Try current price from info first
        info = ticker.info
        price = info.get('regularMarketPrice') or info.get('currentPrice')
        if price is not None:
            return float(price)
        
        # Fallback to recent history
        data = ticker.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
        
        raise ValueError("No price data available")
    except Exception as e:
        logger.error(f"Error retrieving price: {e}")
        raise


def validate_ticker(symbol: str) -> bool:
    """Validate if ticker symbol exists"""
    try:
        ticker = fetch_ticker(symbol)
        info = ticker.info
        valid = bool(info and info.get('regularMarketPrice') is not None)
        if not valid:
            logger.debug(f"Ticker '{symbol}' invalid or no price data")
        return valid
    except Exception as e:
        logger.debug(f"Error validating ticker '{symbol}': {e}")
        return False

def format_response(data: Any, success: bool = True, message: str = "") -> Dict[str, Any]:
    """Standardized response format"""
    return {
        'success': success,
        'data': data,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }