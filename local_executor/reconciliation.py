from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .journal_models import (
    Acknowledgement,
    AccountBinding,
    OrderIntent,
    PositionSnapshot,
    ProviderOrder,
    ReconciliationLock,
    ReconciliationRun,
    SubmissionAttempt,
    Trade,
)
from .mutation import MutationPreflight, MutationRequest
from .rate_budget import LocalRateLimitError
from .topstep_client import (
    ORDER_SIDES,
    ORDER_TYPES,
    LocalOrder,
    LocalPosition,
    LocalProviderError,
    LocalTopstepClient,
    LocalTrade,
)


class ReconciliationError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


@dataclass(frozen=True)
class ReconciliationOutcome:
    classification: str
    authoritative: bool
    matched_provider_order_id: int | None
    lock_active: bool


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )).hexdigest()


class ReconciliationService:
    """Provider-authoritative local reconciliation and restart recovery."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: LocalTopstepClient,
        token: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        search_window: timedelta = timedelta(hours=24),
    ) -> None:
        self._sessions = session_factory
        self._client = client
        self._token = token
        self._clock = clock
        self._search_window = search_window

    def reconcile_before_mutation(self, request: MutationRequest) -> MutationPreflight:
        started = self._clock()
        run_id = self._start_run(request.account_binding_id, "pre_mutation", started)
        try:
            account = self._client.select_exact_account(self._token, request.account_id)
            orders = self._client.search_open_orders(self._token, account_id=request.account_id)
            trades = self._client.search_trades(
                self._token, account_id=request.account_id,
                start=started - self._search_window, end=started,
            )
            positions = self._client.search_open_positions(
                self._token, account_id=request.account_id
            )
            self._persist_snapshot(
                request.account_binding_id, orders, trades, positions,
                intent_id=None, intent_custom_tag=None,
            )
            lock_active, outstanding = self._local_blockers(
                request.account_binding_id, exclude_custom_tag=request.custom_tag
            )
            state_hash = self._provider_state_hash(orders, trades, positions)
            clean = not lock_active
            self._finish_run(
                run_id,
                "clean" if clean and not outstanding else "blocked",
                evidence={
                    "orders": len(orders), "trades": len(trades),
                    "positions": len(positions), "state_hash": state_hash,
                },
                checkpoints=self._checkpoints(started, orders, trades, positions),
            )
            return MutationPreflight(
                exact_account_id=account.id,
                provider_available=True,
                reconciliation_clean=clean,
                local_outstanding_clean=not outstanding,
                market_fresh=True,
                clock_healthy=True,
                rate_budget_available=True,
                provider_state_hash=state_hash,
            )
        except LocalRateLimitError:
            self._fail_run(run_id, request.account_binding_id, "rate_budget_unavailable")
            return self._failed_preflight(request.account_id, "rate_budget")
        except LocalProviderError as exc:
            self._fail_run(run_id, request.account_binding_id, exc.classification)
            return self._failed_preflight(request.account_id, "provider")

    def reconcile_intent(
        self, intent_id: str, *, trigger: str = "ambiguity"
    ) -> ReconciliationOutcome:
        with self._sessions() as session:
            intent = session.get(OrderIntent, intent_id)
            if intent is None:
                raise ReconciliationError("intent_not_found")
            binding = session.get(AccountBinding, intent.account_binding_id)
            if binding is None or not binding.is_active:
                raise ReconciliationError("active_exact_account_required")
            account_id = self._account_id(binding)
            started = self._clock()
            created_at = _aware(intent.created_at)
            immutable = {
                "account_id": account_id,
                "custom_tag": intent.custom_tag,
                "contract_id": intent.contract_id,
                "side": intent.side,
                "order_type": intent.order_type,
                "quantity": intent.quantity,
                "action": intent.action,
                "target_provider_id": intent.target_provider_id,
                "limit_price": intent.limit_price,
                "stop_price": intent.stop_price,
                "trail_price": intent.trail_price,
            }

        run_id = self._start_run(binding.id, trigger, started)
        try:
            self._client.select_exact_account(self._token, account_id)
            orders = self._client.search_orders(
                self._token, account_id=account_id,
                start=created_at - timedelta(minutes=2), end=started,
            )
            trades = self._client.search_trades(
                self._token, account_id=account_id,
                start=created_at - timedelta(minutes=2), end=started,
            )
            positions = self._client.search_open_positions(self._token, account_id=account_id)
        except (LocalProviderError, LocalRateLimitError) as exc:
            classification = getattr(exc, "classification", str(exc))
            self._fail_run(run_id, binding.id, classification)
            self._lock(binding.id, classification)
            return ReconciliationOutcome(classification, False, None, True)

        self._persist_snapshot(
            binding.id, orders, trades, positions,
            intent_id=intent_id, intent_custom_tag=str(immutable["custom_tag"]),
        )
        candidates = self._matching_orders(orders, immutable)
        close_trades = self._matching_close_trades(trades, immutable, created_at)
        inconsistent = self._inconsistent_evidence(candidates, trades, positions, immutable)
        authoritative_close = self._authoritative_close(
            close_trades, positions, immutable
        )
        authoritative_order = len(candidates) == 1 and not inconsistent
        if authoritative_order or authoritative_close:
            match = candidates[0] if authoritative_order else None
            provider_order_id = match.id if match is not None else (
                close_trades[0].order_id if close_trades else None
            )
            self._resolve_authoritative(intent_id, provider_order_id)
            classification = "authoritative_match"
            self._finish_run(
                run_id, classification,
                evidence={
                    "candidate_count": len(candidates),
                    "close_trade_count": len(close_trades),
                    "provider_order_id_hash": _hash(provider_order_id),
                    "immutable_hash": _hash(immutable),
                },
                checkpoints=self._checkpoints(started, orders, trades, positions),
            )
            return ReconciliationOutcome(classification, True, provider_order_id, False)

        classification = (
            "multiple_matches" if len(candidates) > 1
            else "multiple_close_matches" if len(close_trades) > 1
            else "inconsistent_provider_state" if inconsistent
            else "zero_matches"
        )
        self._lock(binding.id, classification)
        self._finish_run(
            run_id, classification,
            evidence={"candidate_count": len(candidates), "immutable_hash": _hash(immutable)},
            checkpoints=self._checkpoints(started, orders, trades, positions),
        )
        return ReconciliationOutcome(classification, False, None, True)

    def recover_startup(self) -> dict[str, tuple[str, ...]]:
        unattempted: list[str] = []
        reconciled: list[str] = []
        locked: list[str] = []
        with self._sessions() as session:
            intents = list(session.scalars(select(OrderIntent).where(
                OrderIntent.state.in_(("committed", "ambiguous", "accepted"))
            )))
            work: list[tuple[str, bool]] = []
            for intent in intents:
                attempt = session.scalar(select(SubmissionAttempt).where(
                    SubmissionAttempt.intent_id == intent.id
                ))
                if attempt is None:
                    unattempted.append(intent.id)
                    continue
                ack = session.scalar(select(Acknowledgement).where(
                    Acknowledgement.attempt_id == attempt.id
                ))
                ambiguous = ack is None or intent.state == "ambiguous" \
                    or (ack is not None and ack.classification in {"pending", "unknown"})
                if ambiguous:
                    work.append((intent.id, ack is None))

        for intent_id, missing_ack in work:
            if missing_ack:
                with self._sessions.begin() as session:
                    intent = session.get(OrderIntent, intent_id)
                    attempt = session.scalar(select(SubmissionAttempt).where(
                        SubmissionAttempt.intent_id == intent_id
                    ))
                    intent.state = "ambiguous"
                    attempt.state = "ambiguous"
            outcome = self.reconcile_intent(intent_id, trigger="startup_recovery")
            (reconciled if outcome.authoritative else locked).append(intent_id)
        return {
            "unattempted": tuple(unattempted),
            "reconciled": tuple(reconciled),
            "locked": tuple(locked),
        }

    def reconcile_account_periodic(self, account_binding_id: str) -> ReconciliationOutcome:
        with self._sessions() as session:
            candidate = session.scalar(select(OrderIntent).where(
                OrderIntent.account_binding_id == account_binding_id,
                OrderIntent.state.in_(("ambiguous", "accepted")),
            ).order_by(OrderIntent.created_at))
        if candidate is None:
            started = self._clock()
            run_id = self._start_run(account_binding_id, "periodic", started)
            self._finish_run(run_id, "no_nonterminal_work", evidence={}, checkpoints={
                "local_ledger_at": _aware(started).isoformat()
            })
            return ReconciliationOutcome("no_nonterminal_work", True, None, False)
        return self.reconcile_intent(candidate.id, trigger="periodic")

    def record_operator_resolution(
        self,
        account_binding_id: str,
        *,
        classification: str,
        evidence_hash: str,
        direct_provider_verified: bool,
    ) -> None:
        allowed = {"verified_no_order", "manual_provider_intervention", "support_escalation"}
        if classification not in allowed or len(evidence_hash) != 64 \
                or not direct_provider_verified:
            raise ReconciliationError("operator_resolution_evidence_required")
        with self._sessions.begin() as session:
            lock = session.scalar(select(ReconciliationLock).where(
                ReconciliationLock.account_binding_id == account_binding_id,
                ReconciliationLock.active.is_(True),
            ))
            if lock is None:
                raise ReconciliationError("active_reconciliation_lock_required")
            lock.active = False
            lock.resolved_at = self._clock()
            lock.resolution_classification = classification
            lock.resolution_evidence = {
                "evidence_hash": evidence_hash,
                "direct_provider_verified": True,
            }
            # Deliberately do not create acknowledgements, provider orders, trades,
            # fills, cancellations, or positions from operator statements.

    def _resolve_authoritative(self, intent_id: str, provider_order_id: int | None) -> None:
        with self._sessions.begin() as session:
            intent = session.get(OrderIntent, intent_id)
            intent.state = "reconciled"
            attempt = session.scalar(select(SubmissionAttempt).where(
                SubmissionAttempt.intent_id == intent_id
            ))
            if attempt is not None:
                attempt.state = "reconciled"
                attempt.completed_at = self._clock()
            lock = session.scalar(select(ReconciliationLock).where(
                ReconciliationLock.account_binding_id == intent.account_binding_id
            ))
            if lock is not None:
                lock.active = False
                lock.resolved_at = self._clock()
                lock.resolution_classification = "authoritative_provider_match"
                lock.resolution_evidence = {
                    "provider_order_id_hash": _hash(provider_order_id)
                }

    @staticmethod
    def _matching_orders(
        orders: tuple[LocalOrder, ...], immutable: dict[str, object]
    ) -> tuple[LocalOrder, ...]:
        if immutable["action"] != "place":
            target = immutable["target_provider_id"]
            matches = tuple(order for order in orders if str(order.id) == str(target))
            if immutable["action"] == "cancel":
                return tuple(order for order in matches if order.status in {2, 3, 4, 5})
            if immutable["action"] == "modify":
                return tuple(order for order in matches if
                             order.size == immutable["quantity"]
                             and (immutable["limit_price"] is None
                                  or order.limit_price == immutable["limit_price"])
                             and (immutable["stop_price"] is None
                                  or order.stop_price == immutable["stop_price"])
                             and (immutable["trail_price"] is None
                                  or order.trail_price is not None))
            return ()
        expected_type = ORDER_TYPES.get(str(immutable["order_type"]))
        expected_side = ORDER_SIDES.get(str(immutable["side"]))
        return tuple(order for order in orders if
                     order.account_id == immutable["account_id"]
                     and order.custom_tag == immutable["custom_tag"]
                     and order.contract_id == immutable["contract_id"]
                     and order.side == expected_side
                     and order.order_type == expected_type
                     and order.size == immutable["quantity"])

    @staticmethod
    def _matching_close_trades(
        trades: tuple[LocalTrade, ...], immutable: dict[str, object], created_at: datetime
    ) -> tuple[LocalTrade, ...]:
        if immutable["action"] not in {"close", "partial_close"}:
            return ()
        opposite_side = 1 if immutable["side"] == "BUY" else 0
        return tuple(trade for trade in trades if
                     trade.account_id == immutable["account_id"]
                     and trade.contract_id == immutable["contract_id"]
                     and trade.side == opposite_side
                     and trade.size == immutable["quantity"]
                     and not trade.voided
                     and ReconciliationService._parse_time(trade.creation_timestamp)
                     >= created_at)

    @staticmethod
    def _authoritative_close(
        close_trades: tuple[LocalTrade, ...],
        positions: tuple[LocalPosition, ...],
        immutable: dict[str, object],
    ) -> bool:
        if immutable["action"] not in {"close", "partial_close"} \
                or len(close_trades) != 1:
            return False
        matching_positions = [position for position in positions
                              if position.contract_id == immutable["contract_id"]]
        if immutable["action"] == "close":
            return not matching_positions
        return len(matching_positions) <= 1

    @staticmethod
    def _inconsistent_evidence(
        candidates: tuple[LocalOrder, ...],
        trades: tuple[LocalTrade, ...],
        positions: tuple[LocalPosition, ...],
        immutable: dict[str, object],
    ) -> bool:
        if len(candidates) != 1:
            return False
        order = candidates[0]
        related_trades = [trade for trade in trades if trade.order_id == order.id and not trade.voided]
        if any(trade.account_id != immutable["account_id"]
               or trade.contract_id != immutable["contract_id"] for trade in related_trades):
            return True
        return any(position.account_id != immutable["account_id"]
                   for position in positions)

    def _persist_snapshot(
        self,
        account_binding_id: str,
        orders: tuple[LocalOrder, ...],
        trades: tuple[LocalTrade, ...],
        positions: tuple[LocalPosition, ...],
        *,
        intent_id: str | None,
        intent_custom_tag: str | None,
    ) -> None:
        with self._sessions.begin() as session:
            for order in orders:
                row = session.scalar(select(ProviderOrder).where(
                    ProviderOrder.account_binding_id == account_binding_id,
                    ProviderOrder.provider_order_id == str(order.id),
                ))
                values = {
                    "intent_id": (intent_id if intent_id is not None
                                  and order.custom_tag == intent_custom_tag else None),
                    "custom_tag": order.custom_tag,
                    "status": str(order.status),
                    "contract_id": order.contract_id,
                    "side": "BUY" if order.side == 0 else "SELL",
                    "quantity": order.size,
                    "observed_at": self._clock(),
                }
                if row is None:
                    session.add(ProviderOrder(
                        account_binding_id=account_binding_id,
                        provider_order_id=str(order.id), **values,
                    ))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            for trade in trades:
                existing = session.scalar(select(Trade).where(
                    Trade.account_binding_id == account_binding_id,
                    Trade.provider_trade_id == str(trade.id),
                ))
                if existing is None:
                    session.add(Trade(
                        account_binding_id=account_binding_id,
                        provider_trade_id=str(trade.id), provider_order_id=str(trade.order_id),
                        contract_id=trade.contract_id,
                        side="BUY" if trade.side == 0 else "SELL", quantity=trade.size,
                        price=trade.price, traded_at=self._parse_time(trade.creation_timestamp),
                    ))
            for position in positions:
                signed = position.size if position.side_type == 1 else -position.size
                session.add(PositionSnapshot(
                    account_binding_id=account_binding_id,
                    contract_id=position.contract_id, quantity=signed,
                    average_price=position.average_price, observed_at=self._clock(),
                ))

    def _local_blockers(
        self, account_binding_id: str, *, exclude_custom_tag: str
    ) -> tuple[bool, bool]:
        with self._sessions() as session:
            lock = session.scalar(select(ReconciliationLock).where(
                ReconciliationLock.account_binding_id == account_binding_id,
                ReconciliationLock.active.is_(True),
            ))
            outstanding = session.scalar(select(OrderIntent.id).where(
                OrderIntent.account_binding_id == account_binding_id,
                OrderIntent.custom_tag != exclude_custom_tag,
                OrderIntent.state.in_(("committed", "ambiguous", "accepted")),
            ))
            return lock is not None, outstanding is not None

    def _start_run(self, binding_id: str, trigger: str, started: datetime) -> str:
        with self._sessions.begin() as session:
            row = ReconciliationRun(
                account_binding_id=binding_id, trigger=trigger, state="running",
                started_at=started, evidence={}, checkpoints={},
            )
            session.add(row)
            session.flush()
            return row.id

    def _finish_run(
        self, run_id: str, classification: str, *,
        evidence: dict[str, object], checkpoints: dict[str, object],
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(ReconciliationRun, run_id)
            row.state = "completed"
            row.result_classification = classification
            row.evidence = evidence
            row.checkpoints = checkpoints
            row.completed_at = self._clock()

    def _fail_run(self, run_id: str, binding_id: str, classification: str) -> None:
        self._finish_run(run_id, classification, evidence={}, checkpoints={})
        self._lock(binding_id, classification)

    def _lock(self, binding_id: str, reason: str) -> None:
        with self._sessions.begin() as session:
            lock = session.scalar(select(ReconciliationLock).where(
                ReconciliationLock.account_binding_id == binding_id
            ))
            if lock is None:
                session.add(ReconciliationLock(
                    account_binding_id=binding_id, active=True, reason=reason,
                    acquired_at=self._clock(),
                ))
            else:
                lock.active = True
                lock.reason = reason
                lock.acquired_at = self._clock()
                lock.resolved_at = None
                lock.resolution_classification = None
                lock.resolution_evidence = None

    @staticmethod
    def _provider_state_hash(
        orders: tuple[LocalOrder, ...], trades: tuple[LocalTrade, ...],
        positions: tuple[LocalPosition, ...],
    ) -> str:
        return _hash({
            "orders": [asdict(item) for item in orders],
            "trades": [asdict(item) for item in trades],
            "positions": [asdict(item) for item in positions],
        })

    @staticmethod
    def _checkpoints(
        observed_at: datetime,
        orders: tuple[LocalOrder, ...], trades: tuple[LocalTrade, ...],
        positions: tuple[LocalPosition, ...],
    ) -> dict[str, object]:
        timestamp = _aware(observed_at).isoformat()
        return {
            "orders_at": timestamp,
            "trades_at": timestamp,
            "positions_at": timestamp,
            "local_ledger_at": timestamp,
            "max_order_id": max((item.id for item in orders), default=None),
            "max_trade_id": max((item.id for item in trades), default=None),
            "position_count": len(positions),
        }

    @staticmethod
    def _failed_preflight(account_id: int, reason: str) -> MutationPreflight:
        return MutationPreflight(
            exact_account_id=account_id,
            provider_available=False,
            reconciliation_clean=False,
            local_outstanding_clean=False,
            market_fresh=False,
            clock_healthy=False,
            rate_budget_available=reason != "rate_budget",
            provider_state_hash="",
        )

    @staticmethod
    def _account_id(binding: AccountBinding) -> int:
        try:
            return int(binding.provider_account_id)
        except ValueError:
            raise ReconciliationError("provider_account_id_invalid") from None

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ReconciliationError("provider_timestamp_malformed") from None
