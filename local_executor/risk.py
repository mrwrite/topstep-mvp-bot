from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .journal_models import (
    MarketInput,
    PolicyVersion,
    ProposedIntent,
    RiskDecision,
    StrategyDecision,
)
from .safety import LocalRiskPolicy
from .strategy import RsiThresholdConfig, evaluate_rsi_threshold


@dataclass(frozen=True)
class RiskSnapshot:
    account_id: str | None
    instrument: str | None
    strategy_version: str | None
    configuration_hash: str | None
    quantity: int | None
    open_position: int | None
    orders_this_session: int | None
    orders_today: int | None
    daily_realized_loss: str | None
    consecutive_losses: int | None
    now: datetime | None
    market_timestamp: datetime | None
    clock_skew_seconds: float | None
    cooldown_until: datetime | None
    reconciliation_clean: bool | None
    telemetry_last_success: datetime | None
    active_kills: tuple[str, ...] | None
    lifecycle_state: str | None


@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    classifications: tuple[str, ...]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def evaluate_pretrade(policy: LocalRiskPolicy, snapshot: RiskSnapshot) -> RiskResult:
    policy.validate()
    missing = [name for name, value in asdict(snapshot).items() if value is None]
    if missing:
        return RiskResult(False, tuple(f"missing_{name}" for name in sorted(missing)))
    reasons: list[str] = []
    now = _aware(snapshot.now)
    market_time = _aware(snapshot.market_timestamp)
    if snapshot.account_id not in policy.allowed_account_ids:
        reasons.append("account_not_allowed")
    if snapshot.instrument not in policy.allowed_instruments:
        reasons.append("instrument_not_allowed")
    if snapshot.strategy_version != policy.strategy_version:
        reasons.append("strategy_version_mismatch")
    if snapshot.configuration_hash != policy.configuration_hash:
        reasons.append("configuration_hash_mismatch")
    if snapshot.quantity != 1:
        reasons.append("quantity_must_equal_one")
    if abs(snapshot.open_position) + snapshot.quantity > policy.max_position:
        reasons.append("position_limit")
    if snapshot.orders_this_session >= policy.max_orders_per_session:
        reasons.append("session_order_limit")
    if snapshot.orders_today >= policy.max_orders_per_day:
        reasons.append("daily_order_limit")
    try:
        loss = abs(min(Decimal(snapshot.daily_realized_loss), Decimal("0")))
        limit = Decimal(policy.max_daily_realized_loss)
        if loss >= limit:
            reasons.append("daily_loss_limit")
    except (InvalidOperation, TypeError):
        reasons.append("daily_loss_invalid")
    if snapshot.consecutive_losses >= policy.max_consecutive_losses:
        reasons.append("consecutive_loss_limit")
    local_now = now.astimezone(ZoneInfo(policy.timezone))
    current_time = local_now.time().replace(tzinfo=None)
    start = datetime.strptime(policy.session_start, "%H:%M:%S").time()
    end = datetime.strptime(policy.session_end, "%H:%M:%S").time()
    if local_now.weekday() not in policy.weekdays or not (start <= current_time <= end):
        reasons.append("outside_schedule")
    data_age = (now - market_time).total_seconds()
    if data_age < 0 or data_age > policy.max_data_age_seconds:
        reasons.append("market_data_stale_or_future")
    if abs(snapshot.clock_skew_seconds) > policy.max_clock_skew_seconds:
        reasons.append("clock_skew")
    if snapshot.cooldown_until is not None and _aware(snapshot.cooldown_until) > now:
        reasons.append("provider_cooldown")
    if snapshot.reconciliation_clean is not True:
        reasons.append("reconciliation_not_clean")
    if snapshot.active_kills:
        reasons.append("active_kill")
    if snapshot.lifecycle_state not in {"practice_armed", "combine_armed", "running"}:
        reasons.append("lifecycle_not_armed")
    telemetry_age = (now - _aware(snapshot.telemetry_last_success)).total_seconds()
    if policy.telemetry_outage_behavior == "halt" and telemetry_age > 0:
        reasons.append("telemetry_required")
    elif policy.telemetry_outage_behavior == "bounded_buffer" \
            and telemetry_age > policy.telemetry_max_offline_seconds:
        reasons.append("telemetry_offline_limit")
    return RiskResult(not reasons, tuple(reasons))


class LocalDecisionEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate_and_persist(
        self,
        *,
        installation_id: str,
        account_id: str,
        instrument: str,
        bars: list[dict[str, Any]],
        market_timestamp: datetime,
        strategy_version: str,
        strategy_config: RsiThresholdConfig,
        policy_version: PolicyVersion,
        risk_snapshot: RiskSnapshot,
        origin: str = "local_provider",
        configuration_source: str = "local",
    ) -> tuple[StrategyDecision, ProposedIntent | None, RiskDecision | None]:
        if origin != "local_provider" or configuration_source != "local":
            raise ValueError("remote_strategy_causation_prohibited")
        canonical_bars = json_dumps(bars)
        input_hash = __import__("hashlib").sha256(canonical_bars.encode("utf-8")).hexdigest()
        market = MarketInput(
            installation_id=installation_id,
            input_identity=__import__("hashlib").sha256(
                f"{instrument}:{market_timestamp.isoformat()}:{input_hash}".encode("utf-8")
            ).hexdigest(),
            contract_id=instrument,
            window_start=datetime.fromisoformat(str(bars[0]["timestamp"])),
            window_end=market_timestamp,
            payload_hash=input_hash,
            source="topstep_simulated",
        )
        self.session.add(market)
        self.session.flush()
        result = evaluate_rsi_threshold([float(bar["close"]) for bar in bars], strategy_config)
        decision = StrategyDecision(
            installation_id=installation_id, market_input_id=market.id,
            strategy_version=strategy_version, configuration_hash=strategy_config.hash(),
            decision=result.signal, rationale=f"{result.rationale}:{result.rsi}",
        )
        self.session.add(decision)
        self.session.flush()
        if result.signal == "HOLD":
            return decision, None, None
        proposal = ProposedIntent(
            installation_id=installation_id, strategy_decision_id=decision.id,
            account_id=account_id, instrument=instrument, side=result.signal,
            quantity=1, order_type="market",
        )
        self.session.add(proposal)
        self.session.flush()
        risk = evaluate_pretrade(LocalRiskPolicy(**policy_version.policy), risk_snapshot)
        risk_row = RiskDecision(
            installation_id=installation_id, proposed_intent_id=proposal.id,
            policy_version_id=policy_version.id, allowed=risk.allowed,
            classifications=list(risk.classifications), input_snapshot=_safe_snapshot(risk_snapshot),
        )
        self.session.add(risk_row)
        self.session.flush()
        return decision, proposal, risk_row


def json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _safe_snapshot(snapshot: RiskSnapshot) -> dict[str, Any]:
    values = asdict(snapshot)
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = value.isoformat()
    return values
