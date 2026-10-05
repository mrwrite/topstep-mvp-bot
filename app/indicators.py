import pandas as pd


def compute_indicators(df):
    """Compute common technical indicators used by the trading bot.

    Currently calculates:
    - Relative Strength Index (RSI)
    - Simple moving averages (fast/slow)
    - Moving Average Convergence Divergence (MACD)

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame expected to contain a ``close`` column.

    Returns
    -------
    pandas.DataFrame
        Original DataFrame with indicator columns appended.
    """

    close = pd.to_numeric(df["close"], errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    average_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    relative_strength = average_gain / average_loss
    df["rsi"] = 100 - (100 / (1 + relative_strength))
    df.loc[(average_loss == 0) & average_gain.notna(), "rsi"] = 100.0

    df["ma_fast"] = close.rolling(window=9, min_periods=9).mean()
    df["ma_slow"] = close.rolling(window=21, min_periods=21).mean()

    fast_ema = close.ewm(span=12, min_periods=12, adjust=False).mean()
    slow_ema = close.ewm(span=26, min_periods=26, adjust=False).mean()
    df["macd"] = fast_ema - slow_ema
    df["macd_signal"] = df["macd"].ewm(span=9, min_periods=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    return df
