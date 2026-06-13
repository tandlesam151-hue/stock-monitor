import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, EMAIndicator


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return RSI series for `Close` prices."""
    return RSIIndicator(df['Close'], window=period).rsi()


def bollinger_bands(df: pd.DataFrame, window: int = 20, window_dev: int = 2) -> pd.DataFrame:
    """Return DataFrame with `upper` and `lower` bands."""
    bb = BollingerBands(df['Close'], window=window, window_dev=window_dev)
    return pd.DataFrame({'bb_upper': bb.bollinger_hband(), 'bb_lower': bb.bollinger_lband(), 'bb_mid': bb.bollinger_mavg()})


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Return MACD line and signal line."""
    macd_obj = MACD(df['Close'], window_slow=slow, window_fast=fast, window_sign=signal)
    return pd.DataFrame({'macd': macd_obj.macd(), 'macd_signal': macd_obj.macd_signal(), 'macd_diff': macd_obj.macd_diff()})


def ema(df: pd.DataFrame, period: int) -> pd.Series:
    """Return EMA series for given period."""
    return EMAIndicator(df['Close'], window=period).ema_indicator()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return ATR series."""
    atr_obj = AverageTrueRange(df['High'], df['Low'], df['Close'], window=period)
    return atr_obj.average_true_range()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Compute VWAP as cumulative(typical_price * volume)/cumulative(volume).

    typical_price = (High + Low + Close) / 3
    """
    tp = (df['High'] + df['Low'] + df['Close']) / 3.0
    cum_tp_vol = (tp * df['Volume']).cumsum()
    cum_vol = df['Volume'].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def volume_ratio(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Return current candle volume divided by `window`-period rolling average volume."""
    roll = df['Volume'].rolling(window=window, min_periods=1).mean()
    return df['Volume'] / roll.replace(0, np.nan)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with indicator columns added.

    Adds: rsi, bb_upper, bb_lower, macd, macd_signal, macd_diff, ema9, ema21, atr, vwap, volume_ratio
    """
    out = df.copy()
    out['rsi'] = rsi(out)
    bb = bollinger_bands(out)
    out = out.join(bb)
    m = macd(out)
    out = out.join(m)
    out['ema9'] = ema(out, 9)
    out['ema21'] = ema(out, 21)
    out['atr'] = atr(out)
    out['vwap'] = vwap(out)
    out['volume_ratio'] = volume_ratio(out)
    return out
