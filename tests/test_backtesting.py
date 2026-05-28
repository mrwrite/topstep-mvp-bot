import pytest

from app import backtesting
from app.tradingview_api import TradingViewAPIError


class _FailingClient:
    def get_ohlc(self, *args, **kwargs):
        raise TradingViewAPIError("boom")


def test_fetch_falls_back_to_topstep(monkeypatch):
    sample = {"t": [1, 2], "o": [1, 1.1], "h": [1.1, 1.2], "l": [0.9, 1.0], "c": [1.0, 1.1], "v": [10, 20]}
    called = {"used": False}

    def fake_topstep(symbol, resolution, start, end):  # noqa: ARG001
        called["used"] = True
        return sample

    monkeypatch.setattr(backtesting, "_fetch_topstep_ohlc", fake_topstep)

    result = backtesting._fetch_ohlc_with_fallback(
        symbol="ES",
        resolution="1",
        start=0,
        end=10,
        client=_FailingClient(),
    )

    assert called["used"] is True
    assert result == sample


@pytest.mark.parametrize("resolution,expected", [("1", 1), ("5", 5), ("60", 60), ("d", 1440)])
def test_coerce_resolution_minutes(resolution, expected):
    assert backtesting._coerce_resolution_minutes(resolution) == expected


def test_coerce_resolution_rejects_invalid():
    with pytest.raises(backtesting.BacktestError):
        backtesting._coerce_resolution_minutes("bad")


def test_run_backtest_handles_fallback(monkeypatch):
    closes = [100 + i * 0.1 for i in range(40)]
    payload = {"t": list(range(len(closes))), "o": closes, "h": closes, "l": closes, "c": closes, "v": [1] * len(closes)}

    monkeypatch.setattr(backtesting, "_fetch_ohlc_with_fallback", lambda *_, **__: payload)

    summary = backtesting.run_backtest(
        symbol="ES",
        resolution="1",
        start=0,
        end=10,
        buy_threshold=20,
        sell_threshold=80,
    )

    assert summary.patterns
    assert summary.assumptions
    assert "do not predict" in summary.assumptions[-1]
    assert summary.signals["hold"] + summary.signals["buy"] + summary.signals["sell"] == len(closes)
