from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Sequence


class StrategyInputError(ValueError):
    pass


def calculate_rsi(closes: Sequence[float], *, period: int = 14) -> float:
    if period <= 1 or len(closes) < period + 1:
        raise StrategyInputError("insufficient_rsi_history")
    values = [float(value) for value in closes[-(period + 1):]]
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    average_gain = sum(max(change, 0.0) for change in changes) / period
    average_loss = sum(max(-change, 0.0) for change in changes) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return round(100 - (100 / (1 + relative_strength)), 8)


@dataclass(frozen=True)
class RsiThresholdConfig:
    period: int
    buy_below: float
    sell_above: float

    def validate(self) -> None:
        if self.period <= 1 or not 0 < self.buy_below < self.sell_above < 100:
            raise StrategyInputError("invalid_rsi_configuration")

    def hash(self) -> str:
        self.validate()
        body = json.dumps({"period": self.period, "buy_below": self.buy_below,
                           "sell_above": self.sell_above}, sort_keys=True,
                          separators=(",", ":"))
        return sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategyResult:
    signal: str
    rationale: str
    rsi: float


def evaluate_rsi_threshold(closes: Sequence[float], config: RsiThresholdConfig) -> StrategyResult:
    config.validate()
    value = calculate_rsi(closes, period=config.period)
    if value < config.buy_below:
        return StrategyResult("BUY", "rsi_below_local_threshold", value)
    if value > config.sell_above:
        return StrategyResult("SELL", "rsi_above_local_threshold", value)
    return StrategyResult("HOLD", "rsi_inside_local_thresholds", value)
