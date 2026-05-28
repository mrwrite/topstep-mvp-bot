from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.backtesting import fetch_market_analysis, run_backtest

router = APIRouter()


class MarketRequest(BaseModel):
    symbol: str = Field(..., description="Instrument symbol, e.g. ES")
    resolution: str = Field("1", description="TradingView resolution (1,3,D,etc)")
    start: int = Field(..., description="Unix timestamp (seconds) for start of window")
    end: int = Field(..., description="Unix timestamp (seconds) for end of window")


class BacktestRequest(MarketRequest):
    buy_threshold: int = Field(30, ge=0, le=100)
    sell_threshold: int = Field(70, ge=0, le=100)


@router.post("/market-analysis")
def market_analysis(request: MarketRequest) -> Dict[str, Any]:
    try:
        return fetch_market_analysis(
            symbol=request.symbol,
            resolution=request.resolution,
            start=request.start,
            end=request.end,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as API error
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest")
def backtest(request: BacktestRequest) -> Dict[str, Any]:
    try:
        summary = run_backtest(
            symbol=request.symbol,
            resolution=request.resolution,
            start=request.start,
            end=request.end,
            buy_threshold=request.buy_threshold,
            sell_threshold=request.sell_threshold,
        )
        return {
            "trades": [trade.__dict__ for trade in summary.trades],
            "total_pnl": summary.total_pnl,
            "wins": summary.wins,
            "losses": summary.losses,
            "signals": summary.signals,
            "patterns": summary.patterns,
            "assumptions": summary.assumptions,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced as API error
        raise HTTPException(status_code=400, detail=str(exc)) from exc
