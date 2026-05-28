"""Backtesting helpers powered by TradingView OHLC data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from config import BASE_URL
from app.auth import get_session_token
from app.indicators import compute_indicators
from app.projectx import get_contract_id
from app.strategy import check_trade_signal
from app.tradingview_api import TradingViewAPIError, TradingViewClient
from app.market_analysis import (
    detect_fair_value_gaps,
    detect_liquidity_sweeps,
    identify_supply_demand_zones,
    ohlc_to_dataframe,
    summarize_market_structure,
)
from app.divergence import detect_divergence


@dataclass
class Trade:
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    pnl: float


@dataclass
class BacktestSummary:
    trades: List[Trade]
    total_pnl: float
    wins: int
    losses: int
    signals: Dict[str, int]
    patterns: Dict[str, Any]
    assumptions: List[str]


class BacktestError(Exception):
    """Raised when a backtest cannot be completed."""


def _coerce_resolution_minutes(resolution: str) -> int:
    """Translate TradingView resolution codes into Topstep minute granularity.

    The Topstep history API accepts a ``unit`` of minutes plus an integer multiplier.
    We therefore map TradingView's string inputs into the minute counts Topstep can
    consume, expanding support beyond the initial 1m/3m guard so the fallback works
    for the dashboard's preset options.
    """

    normalized = resolution.strip().upper()
    if normalized == "D":
        return 24 * 60

    if normalized.isdigit():
        minutes = int(normalized)
        if minutes > 0:
            return minutes

    raise BacktestError(
        "Topstep fallback supports minute or daily resolutions (1,3,5,15,60,D)."
    )


def _fetch_topstep_ohlc(symbol: str, resolution: str, start: int, end: int) -> Dict[str, Any]:
    """Fallback OHLC fetcher that pulls data from Topstep when TradingView fails.

    Returns a TradingView-compatible payload dict containing ``t``, ``o``, ``h``, ``l``,
    ``c``, and ``v`` arrays so the rest of the pipeline remains unchanged.
    """

    minutes = _coerce_resolution_minutes(resolution)

    token = get_session_token()
    contract_id = get_contract_id(symbol, token)
    if not contract_id:
        raise BacktestError(f"Unable to find contract for symbol {symbol}.")

    url = f"{BASE_URL}/api/History/retrieveBars"
    payload = {
        "contractId": contract_id,
        "live": False,
        "startTime": datetime.utcfromtimestamp(start).isoformat() + "Z",
        "endTime": datetime.utcfromtimestamp(end).isoformat() + "Z",
        "unit": 2,  # minutes
        "unitNumber": minutes,
        "limit": 500,
        "includePartialBar": False,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise BacktestError(f"Topstep history fetch failed: {response.text}")

    data = response.json()
    bars = data.get("bars") or []
    if not data.get("success") or not bars:
        raise BacktestError(f"Topstep history response invalid: {data}")

    frame = pd.DataFrame(bars)
    frame["timestamp"] = pd.to_datetime(frame["t"])
    frame.sort_values("timestamp", inplace=True)

    return {
        "t": [int(ts.timestamp()) for ts in frame["timestamp"]],
        "o": frame["o"].tolist(),
        "h": frame["h"].tolist(),
        "l": frame["l"].tolist(),
        "c": frame["c"].tolist(),
        "v": frame.get("v", []).tolist(),
    }


def _fetch_ohlc_with_fallback(
    symbol: str, resolution: str, start: int, end: int, client: Optional[TradingViewClient]
) -> Dict[str, Any]:
    """Try TradingView first; fall back to Topstep if credentials are missing or invalid."""

    try:
        return (client or TradingViewClient()).get_ohlc(symbol, resolution, start, end)
    except (ValueError, TradingViewAPIError, requests.RequestException) as exc:
        # Missing API key or upstream HTTP errors should not kill the endpoint; try Topstep.
        try:
            return _fetch_topstep_ohlc(symbol, resolution, start, end)
        except BacktestError:
            raise
        except Exception as fallback_exc:  # pragma: no cover - defensive for unexpected failures
            raise BacktestError(str(fallback_exc)) from exc


def _generate_signals(df: pd.DataFrame, buy_threshold: int, sell_threshold: int) -> List[str]:
    signals: List[str] = []
    for i in range(len(df)):
        window = df.iloc[: i + 1]
        if window[["rsi", "ma_fast", "ma_slow"]].isnull().any().any():
            signals.append("HOLD")
            continue
        signals.append(check_trade_signal(window, buy_threshold, sell_threshold))
    return signals


def run_backtest(
    symbol: str,
    resolution: str,
    start: int,
    end: int,
    buy_threshold: int = 30,
    sell_threshold: int = 70,
    client: Optional[TradingViewClient] = None,
) -> BacktestSummary:
    """Backtest the RSI strategy against TradingView history."""
    raw = _fetch_ohlc_with_fallback(symbol, resolution, start, end, client)
    df = ohlc_to_dataframe(raw)

    df = compute_indicators(df)
    df["signal"] = _generate_signals(df, buy_threshold, sell_threshold)

    trades: List[Trade] = []
    position: Optional[str] = None
    entry_price = 0.0
    entry_time: Optional[pd.Timestamp] = None

    for timestamp, row in df.iterrows():
        signal = row["signal"]
        price = float(row["close"])

        if signal == "BUY":
            if position == "SHORT":
                pnl = entry_price - price
                trades.append(
                    Trade("SHORT", entry_time.to_pydatetime(), timestamp.to_pydatetime(), entry_price, price, pnl)
                )
                position = None
            if position is None:
                position = "LONG"
                entry_price = price
                entry_time = timestamp

        if signal == "SELL":
            if position == "LONG":
                pnl = price - entry_price
                trades.append(
                    Trade("LONG", entry_time.to_pydatetime(), timestamp.to_pydatetime(), entry_price, price, pnl)
                )
                position = None
            if position is None:
                position = "SHORT"
                entry_price = price
                entry_time = timestamp

    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)
    total_pnl = sum(t.pnl for t in trades)

    pattern_summary = {
        "divergences": len(detect_divergence(df.dropna(subset=["close", "rsi"], how="any"))),
        "liquidity_sweeps": len(detect_liquidity_sweeps(df)),
        "fair_value_gaps": len(detect_fair_value_gaps(df)),
        "supply_demand_zones": len(identify_supply_demand_zones(df)),
    }

    signals_summary = {
        "buy": sum(1 for s in df["signal"] if s == "BUY"),
        "sell": sum(1 for s in df["signal"] if s == "SELL"),
        "hold": sum(1 for s in df["signal"] if s == "HOLD"),
    }

    return BacktestSummary(
        trades=trades,
        total_pnl=total_pnl,
        wins=wins,
        losses=losses,
        signals=signals_summary,
        patterns=pattern_summary,
        assumptions=[
            "Strategy: rsi-threshold-v1 only. Moving averages and momentum are not confirmation signals.",
            "No slippage, commissions, margin, liquidity constraints, or exchange fees are modeled.",
            "Backtest and paper results do not predict or guarantee live trading performance.",
        ],
    )


def fetch_market_analysis(
    symbol: str,
    resolution: str,
    start: int,
    end: int,
    client: Optional[TradingViewClient] = None,
) -> Dict[str, Any]:
    """Pull TradingView data and return market-structure insights."""
    payload = _fetch_ohlc_with_fallback(symbol, resolution, start, end, client)
    df = compute_indicators(ohlc_to_dataframe(payload))
    return summarize_market_structure(df)
