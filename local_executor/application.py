from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from . import __version__
from .control_surface import ControlSurfaceError
from .credentials import CredentialEnrollment
from .journal import LocalJournal
from .journal_models import (
    AccountBinding,
    Consent,
    Installation,
    KillState,
    PolicyVersion,
    QualificationEvidence,
    ReconciliationLock,
    OrderIntent,
    ProviderRateBudget,
)
from .mutation import (
    MutationAuthorization,
    MutationPipeline,
    MutationPipelineError,
    MutationRequest,
)
from .rate_budget import DurableRateLimiter
from .reconciliation import ReconciliationService
from .risk import LocalDecisionEngine, RiskSnapshot
from .runtime import RuntimeDecision
from .safety import LocalRiskPolicy, REQUIRED_PRACTICE_EVIDENCE, SafetyError, SafetyService
from .session import LocalSessionError, MemoryOnlySessionManager
from .strategy import RsiThresholdConfig, StrategyInputError
from .topstep_client import LocalProviderError, LocalTopstepClient


class LocalExecutorApplication:
    """Owns the local journal and read-only provider setup workflow.

    Account identifiers never cross the loopback HTTP boundary. Account discovery
    returns a short-lived opaque handle which is resolved only in this process.
    """

    def __init__(
        self,
        *,
        data_directory: Path,
        enrollment: CredentialEnrollment,
        runtime: RuntimeDecision,
        client: LocalTopstepClient | None = None,
        boot_id: str | None = None,
        journal: LocalJournal | None = None,
    ) -> None:
        self._runtime = runtime
        self._enrollment = enrollment
        self._boot_id = boot_id or str(uuid4())
        self._journal = journal or LocalJournal.open(data_directory / "executor.db")
        limiter = DurableRateLimiter(self._journal.session_factory)
        self._client = client or LocalTopstepClient(limiter)
        self._sessions = MemoryOnlySessionManager(
            enrollment,
            self._client.authenticate,
            self._client.validate_session,
        )
        self._account_handles: dict[str, int] = {}
        self._installation_id = self._prepare_installation()
        self._credential_generation_override: int | None = None

    @property
    def journal(self) -> LocalJournal:
        return self._journal

    def close(self) -> None:
        self._sessions.clear()
        self._account_handles.clear()
        self._journal.close()

    def credentials_changed(self) -> None:
        self._sessions.clear()
        self._account_handles.clear()
        with self._journal.session_factory.begin() as session:
            installation = session.get(Installation, self._installation_id)
            bindings = list(session.scalars(select(AccountBinding).where(
                AccountBinding.installation_id == self._installation_id,
                AccountBinding.is_active.is_(True),
            )))
            if bindings:
                maximum = max(binding.credential_generation for binding in bindings)
                self._credential_generation_override = maximum + 1
                for binding in bindings:
                    binding.is_active = False
            if installation is not None and installation.lifecycle_state not in {
                "disabled", "observe_only"
            }:
                service = SafetyService(session, boot_id=self._boot_id)
                if installation.lifecycle_state != "halted":
                    service.transition(installation, "observe_only", "credentials_changed")

    def health(self) -> dict[str, Any]:
        with self._journal.session_factory() as session:
            installation = session.get(Installation, self._installation_id)
            active_kills = session.scalar(
                select(func.count()).select_from(KillState).where(
                    KillState.installation_id == self._installation_id,
                    KillState.active.is_(True),
                )
            ) or 0
            binding = session.scalar(select(AccountBinding).where(
                AccountBinding.installation_id == self._installation_id,
                AccountBinding.is_active.is_(True),
            ))
            policy = session.scalar(select(PolicyVersion).where(
                PolicyVersion.installation_id == self._installation_id,
                PolicyVersion.is_active.is_(True),
            ))
            return {
                "classification": self._runtime.classification,
                "effective_mode": self._runtime.effective_mode.value,
                "mutation_capable": self._runtime.mutation_capable,
                "lifecycle_state": installation.lifecycle_state if installation else "disabled",
                "account_attested": binding is not None,
                "policy_configured": policy is not None,
                "active_kill_count": int(active_kills),
                "version": __version__,
            }

    def discover_accounts(self) -> dict[str, Any]:
        try:
            token = self._sessions.get_token()
            accounts = self._client.search_active_accounts(token)
        except (LocalSessionError, LocalProviderError) as exc:
            raise ControlSurfaceError(exc.classification, status=409) from None
        self._account_handles.clear()
        safe_accounts: list[dict[str, Any]] = []
        for account in accounts:
            if not account.is_visible:
                continue
            handle = secrets.token_urlsafe(18)
            self._account_handles[handle] = account.id
            safe_accounts.append({
                "selection_handle": handle,
                "redacted_suffix": self._redacted_suffix(account.id),
                "can_trade": account.can_trade,
                "is_visible": account.is_visible,
            })
        return {
            "classification": "accounts_discovered",
            "accounts": safe_accounts,
        }

    def attest_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        handle = payload.get("selection_handle")
        account_kind = payload.get("account_kind")
        confirmation = payload.get("typed_confirmation")
        if not all(isinstance(value, str) and value for value in (
            handle, account_kind, confirmation
        )):
            raise ControlSurfaceError("account_attestation_fields_required")
        account_id = self._account_handles.get(handle)
        if account_id is None:
            raise ControlSurfaceError("account_selection_expired", status=409)
        try:
            token = self._sessions.get_token()
            self._client.select_exact_account(token, account_id)
            with self._journal.session_factory.begin() as session:
                installation = session.get(Installation, self._installation_id)
                generation = self._credential_generation(session)
                binding = SafetyService(session, boot_id=self._boot_id).attest_account(
                    installation,
                    provider_account_id=str(account_id),
                    credential_generation=generation,
                    account_kind=account_kind,
                    typed_confirmation=confirmation,
                )
                classification = f"{binding.account_attestation}_account_attested"
        except (LocalSessionError, LocalProviderError, SafetyError) as exc:
            raise ControlSurfaceError(exc.classification, status=409) from None
        finally:
            self._account_handles.clear()
        return {
            "classification": classification,
            "redacted_suffix": self._redacted_suffix(account_id),
        }

    def policy_status(self) -> dict[str, Any]:
        with self._journal.session_factory() as session:
            row = session.scalar(select(PolicyVersion).where(
                PolicyVersion.installation_id == self._installation_id,
                PolicyVersion.is_active.is_(True),
            ))
            if row is None:
                return {"classification": "policy_review_required", "configured": False}
            return {
                "classification": "policy_configured",
                "configured": True,
                "version": row.version,
                "strategy_version": row.policy.get("strategy_version"),
                "allowed_instruments": row.policy.get("allowed_instruments", []),
            }

    def search_contracts(self, query: dict[str, str]) -> dict[str, Any]:
        search_text = query.get("search", "").strip()
        if len(search_text) < 1 or len(search_text) > 32:
            raise ControlSurfaceError("contract_search_text_required")
        try:
            token = self._sessions.get_token()
            contracts = self._client.search_contracts(token, search_text, live=False)
        except (LocalSessionError, LocalProviderError) as exc:
            raise ControlSurfaceError(exc.classification, status=409) from None
        return {
            "classification": "simulated_contracts_discovered",
            "contracts": [
                {
                    "contract_id": contract.id,
                    "name": contract.name,
                    "active": contract.active,
                    "tick_size": contract.tick_size,
                    "tick_value": contract.tick_value,
                }
                for contract in contracts if contract.active
            ],
        }

    def save_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            strategy = RsiThresholdConfig(
                period=self._integer(payload, "rsi_period"),
                buy_below=self._number(payload, "rsi_buy_below"),
                sell_above=self._number(payload, "rsi_sell_above"),
            )
            strategy.validate()
            with self._journal.session_factory.begin() as session:
                installation = session.get(Installation, self._installation_id)
                binding = self._active_binding(session)
                policy = LocalRiskPolicy(
                    allowed_account_ids=(binding.provider_account_id,),
                    allowed_instruments=(self._text(payload, "instrument"),),
                    strategy_version="rsi-threshold-v1",
                    configuration_hash=strategy.hash(),
                    quantity=1,
                    max_position=self._integer(payload, "max_position"),
                    max_orders_per_session=self._integer(payload, "max_orders_per_session"),
                    max_orders_per_day=self._integer(payload, "max_orders_per_day"),
                    max_daily_realized_loss=self._text(payload, "max_daily_realized_loss"),
                    max_consecutive_losses=self._integer(payload, "max_consecutive_losses"),
                    timezone=self._text(payload, "timezone"),
                    weekdays=tuple(self._integer_list(payload, "weekdays")),
                    session_start=self._text(payload, "session_start"),
                    session_end=self._text(payload, "session_end"),
                    max_data_age_seconds=self._integer(payload, "max_data_age_seconds"),
                    max_clock_skew_seconds=self._integer(payload, "max_clock_skew_seconds"),
                    provider_error_cooldown_seconds=self._integer(
                        payload, "provider_error_cooldown_seconds"
                    ),
                    telemetry_outage_behavior=self._text(
                        payload, "telemetry_outage_behavior"
                    ),
                    telemetry_max_offline_seconds=self._integer(
                        payload, "telemetry_max_offline_seconds", minimum=0
                    ),
                    kill_cancel_open_orders=payload.get("kill_cancel_open_orders") is True,
                    kill_flatten_positions=payload.get("kill_flatten_positions") is True,
                )
                row = SafetyService(session, boot_id=self._boot_id).activate_policy(
                    installation, policy
                )
                version = row.version
        except (ControlSurfaceError, SafetyError, StrategyInputError) as exc:
            classification = getattr(exc, "classification", str(exc))
            raise ControlSurfaceError(classification, status=409) from None
        return {"classification": "policy_saved", "version": version}

    def accept_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("typed_confirmation") != "I UNDERSTAND":
            raise ControlSurfaceError("consent_confirmation_required", status=409)
        try:
            with self._journal.session_factory.begin() as session:
                installation = session.get(Installation, self._installation_id)
                binding = self._active_binding(session)
                policy = self._active_policy(session)
                row = SafetyService(session, boot_id=self._boot_id).accept_consent(
                    installation,
                    binding,
                    policy,
                    strategy_version=str(policy.policy["strategy_version"]),
                    configuration_hash=str(policy.policy["configuration_hash"]),
                    consent_version="local-beta-v1",
                )
                accepted_at = row.accepted_at.isoformat()
        except SafetyError as exc:
            raise ControlSurfaceError(exc.classification, status=409) from None
        return {"classification": "consent_accepted", "accepted_at": accepted_at}

    def arm_practice(self, _payload: dict[str, Any]) -> dict[str, Any]:
        if not self._runtime.mutation_capable:
            raise ControlSurfaceError("signed_mutation_build_required", status=409)
        try:
            with self._journal.session_factory.begin() as session:
                installation = session.get(Installation, self._installation_id)
                binding = self._active_binding(session)
                policy = self._active_policy(session)
                consent = session.scalar(select(Consent).where(
                    Consent.account_binding_id == binding.id,
                    Consent.policy_version_id == policy.id,
                    Consent.revoked_at.is_(None),
                ).order_by(Consent.accepted_at.desc()))
                if consent is None:
                    raise ControlSurfaceError("current_consent_required", status=409)
                SafetyService(session, boot_id=self._boot_id).arm_practice(
                    installation, binding, policy, consent
                )
        except SafetyError as exc:
            raise ControlSurfaceError(exc.classification, status=409) from None
        return {"classification": "practice_armed"}

    def run_practice_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._runtime.mutation_capable:
            raise ControlSurfaceError("signed_mutation_build_required", status=409)
        strategy = RsiThresholdConfig(
            period=self._integer(payload, "rsi_period"),
            buy_below=self._number(payload, "rsi_buy_below"),
            sell_above=self._number(payload, "rsi_sell_above"),
        )
        try:
            strategy.validate()
            token = self._sessions.get_token()
            now = datetime.now(timezone.utc)
            with self._journal.session_factory() as session:
                installation = session.get(Installation, self._installation_id)
                binding = self._active_binding(session)
                policy = self._active_policy(session)
                if installation.lifecycle_state != "practice_armed" \
                        or binding.account_attestation != "practice":
                    raise ControlSurfaceError("practice_not_armed", status=409)
                if strategy.hash() != policy.policy.get("configuration_hash"):
                    raise ControlSurfaceError("strategy_configuration_mismatch", status=409)
                instrument = str(policy.policy["allowed_instruments"][0])
                account_id = int(binding.provider_account_id)
                installation_id = installation.id
                binding_id = binding.id
                policy_id = policy.id
                lifecycle_state = installation.lifecycle_state
                session_started = installation.last_started_at

            self._client.select_exact_account(token, account_id)
            bars = self._client.retrieve_bars(
                token,
                contract_id=instrument,
                start=now - timedelta(days=7),
                end=now,
                unit=2,
                unit_number=5,
                limit=max(strategy.period + 1, 100),
                live=False,
            )
            if len(bars) < strategy.period + 1:
                raise ControlSurfaceError("insufficient_market_history", status=409)
            market_time = self._parse_provider_time(bars[-1].timestamp)
            positions = self._client.search_open_positions(token, account_id=account_id)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            trades = self._client.search_trades(
                token, account_id=account_id, start=day_start, end=now
            )
            snapshot = self._risk_snapshot(
                now=now,
                market_time=market_time,
                account_id=account_id,
                instrument=instrument,
                strategy=strategy,
                lifecycle_state=lifecycle_state,
                session_started=session_started,
                positions=positions,
                trades=trades,
                clock_skew_seconds=self._client.clock_skew_seconds,
            )
            with self._journal.session_factory.begin() as session:
                policy = session.get(PolicyVersion, policy_id)
                decision, proposal, risk = LocalDecisionEngine(session).evaluate_and_persist(
                    installation_id=installation_id,
                    account_id=str(account_id),
                    instrument=instrument,
                    bars=[{
                        "timestamp": bar.timestamp,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    } for bar in bars],
                    market_timestamp=market_time,
                    strategy_version="rsi-threshold-v1",
                    strategy_config=strategy,
                    policy_version=policy,
                    risk_snapshot=snapshot,
                )
            if proposal is None:
                return {
                    "classification": "strategy_hold",
                    "signal": decision.decision,
                    "rationale": decision.rationale,
                }
            if risk is None or not risk.allowed:
                return {
                    "classification": "practice_risk_denied",
                    "signal": decision.decision,
                    "risk_classifications": list(risk.classifications if risk else ()),
                }
            authorization = MutationAuthorization(
                exact_account_id=account_id,
                lifecycle_state=lifecycle_state,
                expires_at=now + timedelta(seconds=60),
                reconciliation_clean=snapshot.reconciliation_clean is True,
                market_fresh=(now - market_time).total_seconds() <= int(
                    policy.policy["max_data_age_seconds"]
                ),
                clock_healthy=abs(float(snapshot.clock_skew_seconds or 0)) <= int(
                    policy.policy["max_clock_skew_seconds"]
                ),
                active_kills=tuple(snapshot.active_kills or ()),
            )
            reconciler = ReconciliationService(
                self._journal.session_factory, self._client, token
            )
            outcome = MutationPipeline(
                self._journal.session_factory, self._client, reconciler
            ).execute(
                token,
                MutationRequest(
                    action="place",
                    installation_id=installation_id,
                    account_binding_id=binding_id,
                    account_id=account_id,
                    strategy_decision_id=decision.id,
                    policy_version_id=policy_id,
                    risk_decision_id=risk.id,
                    contract_id=instrument,
                    side=decision.decision,
                    order_type="market",
                ),
                authorization,
            )
            return {
                "classification": f"practice_order_{outcome.classification}",
                "signal": decision.decision,
                "ambiguous": outcome.ambiguous,
                "direct_topstep_verification_required": outcome.ambiguous,
            }
        except ControlSurfaceError:
            raise
        except (LocalSessionError, LocalProviderError, MutationPipelineError) as exc:
            classification = getattr(exc, "classification", "practice_run_failed")
            raise ControlSurfaceError(classification, status=409) from None
        except (SafetyError, StrategyInputError, ValueError, InvalidOperation):
            raise ControlSurfaceError("practice_run_invalid", status=409) from None

    def qualification_status(self) -> dict[str, Any]:
        with self._journal.session_factory() as session:
            binding = session.scalar(select(AccountBinding).where(
                AccountBinding.installation_id == self._installation_id,
                AccountBinding.account_attestation == "practice",
                AccountBinding.is_active.is_(True),
            ))
            completed: set[str] = set()
            if binding is not None:
                completed = set(session.scalars(select(QualificationEvidence.evidence_type).where(
                    QualificationEvidence.account_binding_id == binding.id,
                    QualificationEvidence.outcome == "passed",
                    QualificationEvidence.invalidated_at.is_(None),
                )))
            missing = sorted(REQUIRED_PRACTICE_EVIDENCE - completed)
            return {
                "classification": "practice_qualified" if not missing and binding else "practice_incomplete",
                "completed": sorted(completed),
                "missing": missing,
            }

    def reconciliation_status(self) -> dict[str, Any]:
        with self._journal.session_factory() as session:
            count = session.scalar(select(func.count()).select_from(ReconciliationLock).where(
                ReconciliationLock.active.is_(True)
            )) or 0
            return {
                "classification": "reconciliation_clean" if count == 0 else "reconciliation_locked",
                "active_lock_count": int(count),
            }

    def _prepare_installation(self) -> str:
        now = datetime.now(timezone.utc)
        with self._journal.session_factory.begin() as session:
            installation = session.scalar(
                select(Installation).order_by(Installation.created_at).limit(1)
            )
            if installation is None:
                installation = Installation(
                    software_version=__version__,
                    lifecycle_state="disabled",
                    last_started_at=now,
                )
                session.add(installation)
                session.flush()
            else:
                installation.software_version = __version__
                installation.last_started_at = now
            service = SafetyService(session, boot_id=self._boot_id)
            service.invalidate_for_restart(installation)
            if installation.lifecycle_state == "disabled":
                service.transition(installation, "observe_only", "local_interactive_start")
            return installation.id

    def _credential_generation(self, session) -> int:
        if self._credential_generation_override is not None:
            return self._credential_generation_override
        maximum = session.scalar(select(func.max(AccountBinding.credential_generation)).where(
            AccountBinding.installation_id == self._installation_id
        ))
        return int(maximum or 1)

    def _risk_snapshot(
        self,
        *,
        now: datetime,
        market_time: datetime,
        account_id: int,
        instrument: str,
        strategy: RsiThresholdConfig,
        lifecycle_state: str,
        session_started: datetime,
        positions,
        trades,
        clock_skew_seconds: float | None,
    ) -> RiskSnapshot:
        open_position = sum(
            position.size if position.side_type == 1 else -position.size
            for position in positions if position.contract_id == instrument
        )
        realized = sum(
            (Decimal(trade.profit_and_loss) if trade.profit_and_loss is not None else Decimal("0"))
            for trade in trades
        )
        consecutive_losses = 0
        for trade in reversed(trades):
            if trade.profit_and_loss is None or Decimal(trade.profit_and_loss) >= 0:
                break
            consecutive_losses += 1
        with self._journal.session_factory() as session:
            orders_this_session = session.scalar(select(func.count()).select_from(OrderIntent).where(
                OrderIntent.installation_id == self._installation_id,
                OrderIntent.created_at >= session_started,
            )) or 0
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            orders_today = session.scalar(select(func.count()).select_from(OrderIntent).where(
                OrderIntent.installation_id == self._installation_id,
                OrderIntent.created_at >= day_start,
            )) or 0
            active_kills = tuple(session.scalars(select(KillState.scope).where(
                KillState.installation_id == self._installation_id,
                KillState.active.is_(True),
            )))
            lock = session.scalar(select(ReconciliationLock.id).where(
                ReconciliationLock.account_binding_id == self._active_binding(session).id,
                ReconciliationLock.active.is_(True),
            ))
            cooldowns = tuple(session.scalars(select(ProviderRateBudget.cooldown_until).where(
                ProviderRateBudget.cooldown_until.is_not(None)
            )))
        cooldown_until = max(cooldowns) if cooldowns else now
        return RiskSnapshot(
            account_id=str(account_id),
            instrument=instrument,
            strategy_version="rsi-threshold-v1",
            configuration_hash=strategy.hash(),
            quantity=1,
            open_position=open_position,
            orders_this_session=int(orders_this_session),
            orders_today=int(orders_today),
            daily_realized_loss=str(realized),
            consecutive_losses=consecutive_losses,
            now=now,
            market_timestamp=market_time,
            clock_skew_seconds=clock_skew_seconds,
            cooldown_until=cooldown_until,
            reconciliation_clean=lock is None,
            # Until outbound delivery is configured, startup begins the bounded
            # telemetry-outage budget. A halt policy still denies immediately.
            telemetry_last_success=session_started,
            active_kills=active_kills,
            lifecycle_state=lifecycle_state,
        )

    @staticmethod
    def _parse_provider_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ControlSurfaceError("provider_timestamp_malformed", status=409) from None
        if parsed.tzinfo is None:
            raise ControlSurfaceError("provider_timestamp_malformed", status=409)
        return parsed.astimezone(timezone.utc)

    def _active_binding(self, session) -> AccountBinding:
        row = session.scalar(select(AccountBinding).where(
            AccountBinding.installation_id == self._installation_id,
            AccountBinding.is_active.is_(True),
        ))
        if row is None:
            raise ControlSurfaceError("active_exact_account_required", status=409)
        return row

    def _active_policy(self, session) -> PolicyVersion:
        row = session.scalar(select(PolicyVersion).where(
            PolicyVersion.installation_id == self._installation_id,
            PolicyVersion.is_active.is_(True),
        ))
        if row is None:
            raise ControlSurfaceError("active_policy_required", status=409)
        return row

    @staticmethod
    def _text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ControlSurfaceError(f"{key}_required")
        return value.strip()

    @staticmethod
    def _integer(
        payload: dict[str, Any], key: str, *, minimum: int = 1
    ) -> int:
        value = payload.get(key)
        if isinstance(value, bool):
            raise ControlSurfaceError(f"{key}_invalid")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ControlSurfaceError(f"{key}_invalid") from None
        if parsed < minimum:
            raise ControlSurfaceError(f"{key}_invalid")
        return parsed

    @staticmethod
    def _number(payload: dict[str, Any], key: str) -> float:
        try:
            return float(payload.get(key))
        except (TypeError, ValueError):
            raise ControlSurfaceError(f"{key}_invalid") from None

    @staticmethod
    def _integer_list(payload: dict[str, Any], key: str) -> list[int]:
        value = payload.get(key)
        if not isinstance(value, list):
            raise ControlSurfaceError(f"{key}_invalid")
        try:
            return [int(item) for item in value]
        except (TypeError, ValueError):
            raise ControlSurfaceError(f"{key}_invalid") from None

    @staticmethod
    def _redacted_suffix(account_id: int) -> str:
        return f"****{str(account_id)[-4:]}"
