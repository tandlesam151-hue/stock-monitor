import logging
import yfinance as yf

logger = logging.getLogger(__name__)

def get_price(symbol: str) -> dict:
    """Fetch current price data for symbol using yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="5m")
        if hist.empty:
            logger.warning(f"No data retrieved for {symbol}")
            return {}
        
        latest = hist.iloc[-1]
        open_price = hist.iloc[0]["Open"]
        
        return {
            "symbol" : symbol,
            "open"   : round(open_price, 2),
            "current": round(latest["Close"], 2),
            "high"   : round(hist["High"].max(), 2),
            "low"    : round(hist["Low"].min(), 2),
            "volume" : int(latest["Volume"]),
            "pct_chg": round((latest["Close"] - open_price) / open_price * 100, 2),
        }
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return {}