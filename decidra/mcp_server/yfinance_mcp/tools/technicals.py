import pandas as pd
import numpy as np
from typing import Dict, List
import yfinance as yf

class TechnicalIndicators:
    """
    Class that provides various technical indicators and analysis tools for stock data.
    """
    
    @staticmethod
    def get_stock_data(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        """
        Retrieve historical stock data for technical analysis.
        
        Args:
            symbol: Stock ticker symbol
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
            
        Returns:
            DataFrame with historical stock data
        """
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period, interval=interval)
            if data.empty:
                raise ValueError(f"No data found for {symbol}")
            return data
        except Exception as e:
            raise ValueError(f"Error retrieving data for {symbol}: {e}")
    
    @staticmethod
    def calculate_moving_average(data: pd.DataFrame, window: int, column: str = 'Close') -> pd.Series:
        """
        Calculate simple moving average.
        
        Args:
            data: DataFrame with price data
            window: Period for moving average
            column: Column name to calculate MA for (default: Close)
            
        Returns:
            Series with moving average values
        """
        return data[column].rolling(window=window).mean()
    
    @staticmethod
    def calculate_exponential_moving_average(data: pd.DataFrame, window: int, column: str = 'Close') -> pd.Series:
        """
        Calculate exponential moving average.
        
        Args:
            data: DataFrame with price data
            window: Period for EMA
            column: Column name to calculate EMA for (default: Close)
            
        Returns:
            Series with EMA values
        """
        return data[column].ewm(span=window, adjust=False).mean()
    
    @staticmethod
    def calculate_rsi(data: pd.DataFrame, window: int = 14, column: str = 'Close') -> pd.Series:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            data: DataFrame with price data
            window: RSI period (default: 14)
            column: Column name to calculate RSI for (default: Close)
            
        Returns:
            Series with RSI values
        """
        delta = data[column].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=window).mean()
        avg_loss = loss.rolling(window=window).mean()
        
        
        for i in range(window, len(delta)):
            if i > window:  
                avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (window-1) + gain.iloc[i]) / window
                avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (window-1) + loss.iloc[i]) / window

        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_macd(data: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, 
                      signal_period: int = 9, column: str = 'Close') -> Dict[str, pd.Series]:
        """
        Calculate Moving Average Convergence Divergence (MACD).
        
        Args:
            data: DataFrame with price data
            fast_period: Fast EMA period (default: 12)
            slow_period: Slow EMA period (default: 26)
            signal_period: Signal line period (default: 9)
            column: Column name to calculate MACD for (default: Close)
            
        Returns:
            Dictionary with 'macd', 'signal', and 'histogram' Series
        """
        fast_ema = TechnicalIndicators.calculate_exponential_moving_average(data, fast_period, column)
        slow_ema = TechnicalIndicators.calculate_exponential_moving_average(data, slow_period, column)
        
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }
    
    @staticmethod
    def calculate_bollinger_bands(data: pd.DataFrame, window: int = 20, 
                                num_std: float = 2.0, column: str = 'Close') -> Dict[str, pd.Series]:
        """
        Calculate Bollinger Bands.
        
        Args:
            data: DataFrame with price data
            window: Moving average period (default: 20)
            num_std: Number of standard deviations (default: 2.0)
            column: Column name for calculation (default: Close)
            
        Returns:
            Dictionary with 'upper', 'middle', and 'lower' bands as Series
        """
        middle_band = TechnicalIndicators.calculate_moving_average(data, window, column)
        std_dev = data[column].rolling(window=window).std()
        
        upper_band = middle_band + (std_dev * num_std)
        lower_band = middle_band - (std_dev * num_std)
        
        return {
            'upper': upper_band,
            'middle': middle_band,
            'lower': lower_band
        }
    
    @staticmethod
    def calculate_atr(data: pd.DataFrame, window: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR).
        
        Args:
            data: DataFrame with price data
            window: ATR period (default: 14)
            
        Returns:
            Series with ATR values
        """
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        # Calculate True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=window).mean()
        
        return atr
    
    @staticmethod
    def calculate_volatility(data: pd.DataFrame, window: int = 20, column: str = 'Close', 
                           annualize: bool = True) -> pd.Series:
        """
        Calculate rolling volatility.
        
        Args:
            data: DataFrame with price data
            window: Period for volatility calculation (default: 20)
            column: Column name to calculate volatility for (default: Close)
            annualize: Whether to annualize the volatility (default: True)
            
        Returns:
            Series with volatility values
        """
        # Calculate logarithmic returns
        log_returns = np.log(data[column] / data[column].shift(1))
        
        # Calculate rolling standard deviation
        volatility = log_returns.rolling(window=window).std()
        
        # Annualize if requested (assuming 252 trading days)
        if annualize:
            if 'd' in data.index.freq or data.index.freq is None:  # Daily data
                volatility = volatility * np.sqrt(252)
            elif 'h' in data.index.freq:  # Hourly data
                volatility = volatility * np.sqrt(252 * 6.5)  # ~6.5 trading hours per day
            elif 'm' in data.index.freq:  # Minute data
                volatility = volatility * np.sqrt(252 * 6.5 * 60)
                
        return volatility
    
    
    @staticmethod
    def detect_support_resistance(data: pd.DataFrame, window: int = 20, sensitivity: float = 0.03) -> Dict[str, List[float]]:
        """
        Detect support and resistance levels using local minima and maxima.
        """
        try:
            if data is None or data.empty or len(data) < (2 * window + 1):
                return {'support': [], 'resistance': []}

            high = data['High']
            low = data['Low']

            resistance_levels = []
            support_levels = []

            for i in range(window, len(high) - window):
                if all(high[i] > high[i - j] for j in range(1, window + 1)) and \
                all(high[i] > high[i + j] for j in range(1, window + 1)):
                    if not any(abs(high[i] - level) / level < sensitivity for level in resistance_levels):
                        resistance_levels.append(high[i])

            for i in range(window, len(low) - window):
                if all(low[i] < low[i - j] for j in range(1, window + 1)) and \
                all(low[i] < low[i + j] for j in range(1, window + 1)):
                    if not any(abs(low[i] - level) / level < sensitivity for level in support_levels):
                        support_levels.append(low[i])

            return {
                'support': sorted(support_levels),
                'resistance': sorted(resistance_levels)
            }

        except Exception as e:
            print(f"[ERROR] detect_support_resistance: {e}")
            return {'support': [], 'resistance': []}

    
    @staticmethod
    def detect_trends(data: pd.DataFrame, short_window: int = 20, long_window: int = 50, 
                    column: str = 'Close') -> Dict[str, pd.Series]:
        """
        Detect trends using moving average crossovers.
        
        Args:
            data: DataFrame with price data
            short_window: Short-term MA period (default: 20)
            long_window: Long-term MA period (default: 50)
            column: Column name to detect trends for (default: Close)
            
        Returns:
            Dictionary with 'trend' and 'signal' Series
        """
        short_ma = TechnicalIndicators.calculate_moving_average(data, short_window, column)
        long_ma = TechnicalIndicators.calculate_moving_average(data, long_window, column)
        
        # Create trend indicator (1: uptrend, -1: downtrend, 0: neutral/undefined)
        trend = pd.Series(0, index=data.index)
        trend[short_ma > long_ma] = 1  # Uptrend
        trend[short_ma < long_ma] = -1  # Downtrend
        
        # Create signal for trend changes
        signal = pd.Series(0, index=data.index)
        signal[(trend.shift(1) <= 0) & (trend > 0)] = 1  # Buy signal (trend turning positive)
        signal[(trend.shift(1) >= 0) & (trend < 0)] = -1  # Sell signal (trend turning negative)
        
        return {
            'trend': trend,
            'signal': signal
        }
    
    @staticmethod
    def calculate_pattern_recognition(data: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Basic pattern recognition for common candlestick patterns.
        
        Args:
            data: DataFrame with price data (must have Open, High, Low, Close)
            
        Returns:
            Dictionary with pattern signals (1 where pattern is detected)
        """
        pattern_signals = {}
        
        # Doji pattern (open and close are very close)
        doji = pd.Series(0, index=data.index)
        body_size = abs(data['Close'] - data['Open'])
        avg_body = body_size.rolling(window=14).mean()
        shadow_size = data['High'] - data['Low']
        doji[(body_size < 0.1 * shadow_size) & (body_size < 0.25 * avg_body)] = 1
        pattern_signals['doji'] = doji
        
        # Hammer pattern (long lower shadow, small body at the top)
        hammer = pd.Series(0, index=data.index)
        lower_shadow = pd.Series(0, index=data.index)
        upper_shadow = pd.Series(0, index=data.index)
        
        # For days with close > open (bullish)
        bullish = data['Close'] > data['Open']
        lower_shadow[bullish] = data['Open'][bullish] - data['Low'][bullish]
        upper_shadow[bullish] = data['High'][bullish] - data['Close'][bullish]
        
        # For days with open > close (bearish)
        bearish = data['Open'] > data['Close']
        lower_shadow[bearish] = data['Close'][bearish] - data['Low'][bearish]
        upper_shadow[bearish] = data['High'][bearish] - data['Open'][bearish]
        
        # Hammer criteria
        body_height = abs(data['Close'] - data['Open'])
        hammer[(lower_shadow > 2 * body_height) & (upper_shadow < 0.2 * body_height)] = 1
        pattern_signals['hammer'] = hammer
        
        # Engulfing pattern (current candle completely engulfs previous candle)
        bullish_engulfing = pd.Series(0, index=data.index)
        bearish_engulfing = pd.Series(0, index=data.index)
        
        # Bullish engulfing
        bullish_engulfing[(data['Open'] < data['Close'].shift(1)) & 
                         (data['Close'] > data['Open'].shift(1)) &
                         (data['Close'] > data['Open']) &
                         (data['Open'].shift(1) > data['Close'].shift(1))] = 1
        
        # Bearish engulfing
        bearish_engulfing[(data['Open'] > data['Close'].shift(1)) & 
                         (data['Close'] < data['Open'].shift(1)) &
                         (data['Close'] < data['Open']) &
                         (data['Open'].shift(1) < data['Close'].shift(1))] = 1
        
        pattern_signals['bullish_engulfing'] = bullish_engulfing
        pattern_signals['bearish_engulfing'] = bearish_engulfing
        
        return pattern_signals
    
    @staticmethod
    def detect_divergence(data: pd.DataFrame, indicator: pd.Series, window: int = 14) -> Dict[str, pd.Series]:
        """
        Detect divergence between price and indicator (e.g., RSI).
        
        Args:
            data: DataFrame with price data
            indicator: Series with indicator values (e.g., RSI)
            window: Lookback period for finding pivots (default: 14)
            
        Returns:
            Dictionary with 'bullish_divergence' and 'bearish_divergence' Series
        """
        close = data['Close']
        
        bullish_divergence = pd.Series(0, index=data.index)
        bearish_divergence = pd.Series(0, index=data.index)
        
        # Find local price lows and indicator lows
        for i in range(window, len(close) - window):
            # Check for price making lower low
            if (close[i] < close[i-1]) and (close[i] < close[i+1]) and \
               (close[i] < min(close[i-window:i])) and (close[i] < min(close[i+1:i+window+1])):
                
                # But indicator making higher low (bullish divergence)
                if (indicator[i] > indicator[i-window]) and (indicator[i] > indicator[i-window//2]):
                    bullish_divergence[i] = 1
        
        # Find local price highs and indicator highs
        for i in range(window, len(close) - window):
            # Check for price making higher high
            if (close[i] > close[i-1]) and (close[i] > close[i+1]) and \
               (close[i] > max(close[i-window:i])) and (close[i] > max(close[i+1:i+window+1])):
                
                # But indicator making lower high (bearish divergence)
                if (indicator[i] < indicator[i-window]) and (indicator[i] < indicator[i-window//2]):
                    bearish_divergence[i] = 1
        
        return {
            'bullish_divergence': bullish_divergence,
            'bearish_divergence': bearish_divergence
        }

