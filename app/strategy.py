STRATEGY_NAME = "rsi-threshold-v1"
STRATEGY_VERSION = "1.0.0"
STRATEGY_DESCRIPTION = (
    "RSI-threshold strategy. Emits BUY below the configured RSI buy threshold, "
    "SELL above the configured RSI sell threshold, otherwise HOLD. Moving "
    "averages and momentum indicators are computed for inspection only and are "
    "not confirmation signals in this version."
)


def check_trade_signal(df, buy_threshold: int = 30, sell_threshold: int = 70):
    """Return BUY/SELL/HOLD for rsi-threshold-v1."""
    rsi = df["rsi"].iloc[-1]

    if rsi < buy_threshold:
        return "BUY"
    if rsi > sell_threshold:
        return "SELL"
    return "HOLD"
