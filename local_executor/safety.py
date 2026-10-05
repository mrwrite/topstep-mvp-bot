from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from .journal_models import (
    AccountBinding,
    ActivationGrant,
    Consent,
    Installation,
    KillState,
    LifecycleTransition,
    PolicyVersion,
    QualificationEvidence,
    utc_now,
)


class SafetyError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


LIFECYCLE_STATES = (
    "disabled", "observe_only", "practice_armed", "practice_qualified",
    "combine_pending", "combine_armed", "running", "halted",
)
_TRANSITIONS = {
    "disabled": {"observe_only", "halted"},
    "observe_only": {"practice_armed", "halted"},
    "practice_armed": {"practice_qualified", "observe_only", "halted"},
    "practice_qualified": {"combine_pending", "observe_only", "halted"},
    "combine_pending": {"combine_armed", "observe_only", "halted"},
    "combine_armed": {"running", "observe_only", "halted"},
    "running": {"observe_only", "halted"},
    "halted": {"observe_only"},
}
MUTATION_STATES = frozenset({"practice_armed", "combine_armed", "running"})
REQUIRED_PRACTICE_EVIDENCE = frozenset({
    "order_lifecycle", "risk_rejection", "cancellation", "restart_recovery",
    "ambiguity_handling", "reconciliation", "kill_drill",
})


@dataclass(frozen=True)
class LocalRiskPolicy:
    allowed_account_ids: tuple[str, ...]
    allowed_instruments: tuple[str, ...]
    strategy_version: str
    configuration_hash: str
    quantity: int
    max_position: int
    max_orders_per_session: int
    max_orders_per_day: int
    max_daily_realized_loss: str
    max_consecutive_losses: int
    timezone: str
    weekdays: tuple[int, ...]
    session_start: str
    session_end: str
    max_data_age_seconds: int
    max_clock_skew_seconds: int
    provider_error_cooldown_seconds: int
    telemetry_outage_behavior: str
    telemetry_max_offline_seconds: int
    kill_cancel_open_orders: bool
    kill_flatten_positions: bool

    def validate(self) -> None:
        if not self.allowed_account_ids or any(not value.strip() for value in self.allowed_account_ids) \
                or not self.allowed_instruments:
            raise SafetyError("policy_exact_allowlists_required")
        if any(not item.strip() for item in self.allowed_instruments):
            raise SafetyError("policy_exact_allowlists_required")
        if not self.strategy_version.strip() or not self.configuration_hash.strip():
            raise SafetyError("policy_strategy_binding_required")
        if self.quantity != 1:
            raise SafetyError("policy_quantity_must_equal_one")
        positive = (
            self.max_position, self.max_orders_per_session, self.max_orders_per_day,
            self.max_consecutive_losses, self.max_data_age_seconds,
            self.max_clock_skew_seconds, self.provider_error_cooldown_seconds,
        )
        if any(value <= 0 for value in positive):
            raise SafetyError("policy_positive_limits_required")
        try:
            if float(self.max_daily_realized_loss) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise SafetyError("policy_daily_loss_limit_required") from None
        if not self.weekdays or any(day not in range(7) for day in self.weekdays):
            raise SafetyError("policy_schedule_required")
        try:
            ZoneInfo(self.timezone)
            time.fromisoformat(self.session_start)
            time.fromisoformat(self.session_end)
        except (ZoneInfoNotFoundError, ValueError):
            raise SafetyError("policy_schedule_required") from None
        if self.telemetry_outage_behavior not in {"halt", "bounded_buffer"}:
            raise SafetyError("policy_telemetry_behavior_required")
        if self.telemetry_outage_behavior == "bounded_buffer" and self.telemetry_max_offline_seconds <= 0:
            raise SafetyError("policy_telemetry_offline_limit_required")
        if not isinstance(self.kill_cancel_open_orders, bool) or not isinstance(
            self.kill_flatten_positions, bool
        ):
            raise SafetyError("policy_kill_behavior_required")

    def canonical(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        value["allowed_account_ids"] = sorted(set(self.allowed_account_ids))
        value["allowed_instruments"] = sorted(set(self.allowed_instruments))
        value["weekdays"] = sorted(set(self.weekdays))
        return value

    def checksum(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class SafetyService:
    def __init__(self, session: Session, *, boot_id: str, clock=utc_now) -> None:
        try:
            UUID(boot_id)
        except ValueError:
            raise ValueError("boot_id_must_be_uuid") from None
        self.session = session
        self.boot_id = boot_id
        self.clock = clock

    def transition(self, installation: Installation, to_state: str, reason: str) -> None:
        if to_state not in LIFECYCLE_STATES or to_state not in _TRANSITIONS[installation.lifecycle_state]:
            raise SafetyError("lifecycle_transition_denied")
        prior = installation.lifecycle_state
        installation.lifecycle_state = to_state
        self.session.add(LifecycleTransition(
            installation_id=installation.id, from_state=prior, to_state=to_state, reason=reason,
        ))
        self.session.flush()

    def invalidate_for_restart(self, installation: Installation) -> None:
        now = self.clock()
        for grant in self.session.scalars(select(ActivationGrant).where(
            ActivationGrant.installation_id == installation.id,
            ActivationGrant.state.in_(("armed", "first_order_used")),
        )):
            grant.state = "invalidated"
            grant.invalidated_at = now
        if installation.lifecycle_state in MUTATION_STATES or installation.lifecycle_state == "combine_pending":
            self.transition(installation, "observe_only", "process_restart")

    def activate_policy(
        self, installation: Installation, policy: LocalRiskPolicy, *, source: str = "local"
    ) -> PolicyVersion:
        if source != "local":
            raise SafetyError("remote_policy_prohibited")
        canonical = policy.canonical()
        current = self.session.scalar(select(PolicyVersion).where(
            PolicyVersion.installation_id == installation.id,
            PolicyVersion.is_active.is_(True),
        ))
        if current is not None and current.checksum == policy.checksum():
            return current
        version = 1 if current is None else current.version + 1
        if current is not None:
            current.is_active = False
        row = PolicyVersion(
            installation_id=installation.id, version=version, checksum=policy.checksum(),
            policy=canonical, is_active=True,
        )
        self.session.add(row)
        self._invalidate_authorization(installation, "policy_changed")
        self.session.flush()
        return row

    def attest_account(
        self,
        installation: Installation,
        *,
        provider_account_id: str,
        credential_generation: int,
        account_kind: str,
        typed_confirmation: str,
    ) -> AccountBinding:
        if account_kind in {"express_funded", "live_funded", "live_brokerage", "funded"}:
            raise SafetyError("funded_or_live_account_prohibited")
        if account_kind not in {"practice", "trading_combine"}:
            raise SafetyError("account_attestation_required")
        if credential_generation <= 0 or len(provider_account_id) < 4:
            raise SafetyError("exact_account_required")
        suffix = provider_account_id[-4:]
        if typed_confirmation != f"CONFIRM-{suffix}":
            raise SafetyError("account_suffix_confirmation_failed")
        active_bindings = list(self.session.scalars(select(AccountBinding).where(
            AccountBinding.installation_id == installation.id,
            AccountBinding.is_active.is_(True),
        )))
        same_kind = [row for row in active_bindings if row.account_attestation == account_kind]
        credential_changed = any(
            row.credential_generation != credential_generation for row in active_bindings
        )
        for prior in same_kind:
            prior.is_active = False
        row = AccountBinding(
            installation_id=installation.id,
            credential_generation=credential_generation,
            provider_account_id=provider_account_id,
            provider_account_hash=sha256(
                f"{installation.id}:{provider_account_id}".encode("utf-8")
            ).hexdigest(),
            account_attestation=account_kind,
            is_active=True,
        )
        self.session.add(row)
        if same_kind or credential_changed:
            self._invalidate_authorization(installation, "account_or_credential_changed")
        else:
            self._invalidate_grants_and_consents(installation)
        self.session.flush()
        return row

    @staticmethod
    def redacted_account_suffix(provider_account_id: str) -> str:
        return f"••••{provider_account_id[-4:]}"

    def accept_consent(
        self,
        installation: Installation,
        binding: AccountBinding,
        policy: PolicyVersion,
        *,
        strategy_version: str,
        configuration_hash: str,
        consent_version: str,
    ) -> Consent:
        self._assert_binding(installation, binding, policy, strategy_version, configuration_hash)
        now = self.clock()
        for prior in self.session.scalars(select(Consent).where(
            Consent.installation_id == installation.id,
            Consent.account_binding_id == binding.id,
            Consent.revoked_at.is_(None),
        )):
            prior.revoked_at = now
        row = Consent(
            installation_id=installation.id, account_binding_id=binding.id,
            policy_version_id=policy.id, credential_generation=binding.credential_generation,
            strategy_version=strategy_version, configuration_hash=configuration_hash,
            consent_version=consent_version,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def record_practice_evidence(
        self,
        installation: Installation,
        binding: AccountBinding,
        policy: PolicyVersion,
        evidence_type: str,
        *,
        outcome: str,
        strategy_version: str,
        configuration_hash: str,
    ) -> QualificationEvidence:
        if binding.account_attestation != "practice":
            raise SafetyError("practice_account_required")
        if evidence_type not in REQUIRED_PRACTICE_EVIDENCE or outcome not in {"passed", "failed"}:
            raise SafetyError("qualification_evidence_invalid")
        row = QualificationEvidence(
            installation_id=installation.id, account_binding_id=binding.id,
            evidence_type=evidence_type, outcome=outcome,
            evidence={"policy_checksum": policy.checksum, "strategy_version": strategy_version,
                      "configuration_hash": configuration_hash,
                      "credential_generation": binding.credential_generation},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def qualification_complete(
        self, installation: Installation, binding: AccountBinding, policy: PolicyVersion,
        *, strategy_version: str, configuration_hash: str,
    ) -> bool:
        rows = self.session.scalars(select(QualificationEvidence).where(
            QualificationEvidence.installation_id == installation.id,
            QualificationEvidence.account_binding_id == binding.id,
            QualificationEvidence.outcome == "passed",
            QualificationEvidence.invalidated_at.is_(None),
        )).all()
        valid = {
            row.evidence_type for row in rows
            if row.evidence.get("policy_checksum") == policy.checksum
            and row.evidence.get("strategy_version") == strategy_version
            and row.evidence.get("configuration_hash") == configuration_hash
            and row.evidence.get("credential_generation") == binding.credential_generation
        }
        return valid == REQUIRED_PRACTICE_EVIDENCE

    def set_kill(self, installation: Installation, *, scope: str, scope_key: str,
                 active: bool, reason: str) -> KillState:
        row = self.session.scalar(select(KillState).where(
            KillState.installation_id == installation.id,
            KillState.scope == scope, KillState.scope_key == scope_key,
        ))
        now = self.clock()
        if row is None:
            row = KillState(installation_id=installation.id, scope=scope, scope_key=scope_key,
                            active=active, reason=reason, activated_at=now,
                            cleared_at=None if active else now)
            self.session.add(row)
        else:
            row.active = active
            row.reason = reason
            row.version += 1
            row.activated_at = now if active else row.activated_at
            row.cleared_at = None if active else now
        if active and installation.lifecycle_state != "halted":
            self.transition(installation, "halted", f"kill:{scope}")
        self.session.flush()
        return row

    def arm_practice(self, installation: Installation, binding: AccountBinding,
                     policy: PolicyVersion, consent: Consent) -> None:
        self._authorize_common(installation, binding, policy, consent)
        if binding.account_attestation != "practice":
            raise SafetyError("practice_account_required")
        self.transition(installation, "practice_armed", "local_practice_arm")

    def mark_practice_qualified(self, installation: Installation, binding: AccountBinding,
                                policy: PolicyVersion) -> None:
        data = policy.policy
        if not self.qualification_complete(
            installation, binding, policy, strategy_version=data["strategy_version"],
            configuration_hash=data["configuration_hash"],
        ):
            raise SafetyError("practice_qualification_incomplete")
        self.transition(installation, "practice_qualified", "practice_evidence_complete")

    def prepare_combine(self, installation: Installation) -> None:
        self.transition(installation, "combine_pending", "local_combine_preparation")

    def arm_combine(
        self, installation: Installation, binding: AccountBinding, policy: PolicyVersion,
        consent: Consent, *, ttl_seconds: int = 900,
    ) -> ActivationGrant:
        self._authorize_common(installation, binding, policy, consent)
        if binding.account_attestation != "trading_combine":
            raise SafetyError("trading_combine_attestation_required")
        if not 1 <= ttl_seconds <= 900:
            raise SafetyError("combine_arm_ttl_invalid")
        now = self.clock()
        row = ActivationGrant(
            installation_id=installation.id, account_binding_id=binding.id,
            policy_version_id=policy.id, consent_id=consent.id,
            credential_generation=binding.credential_generation,
            strategy_version=policy.policy["strategy_version"],
            configuration_hash=policy.policy["configuration_hash"], boot_id=self.boot_id,
            armed_at=now, expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self.session.add(row)
        self.transition(installation, "combine_armed", "local_combine_arm")
        self.session.flush()
        return row

    def authorize_first_order(self, installation: Installation, grant: ActivationGrant,
                              *, intent_fingerprint: str, typed_confirmation: str,
                              ttl_seconds: int = 120) -> None:
        self._assert_grant(installation, grant)
        binding = self.session.get(AccountBinding, grant.account_binding_id)
        suffix = binding.provider_account_id[-4:]
        if typed_confirmation != f"AUTHORIZE-{suffix}":
            raise SafetyError("first_order_confirmation_failed")
        now = self.clock()
        grant.first_intent_hash = sha256(intent_fingerprint.encode("utf-8")).hexdigest()
        grant.first_intent_authorized_at = now
        grant.first_intent_expires_at = now + timedelta(seconds=max(1, min(ttl_seconds, 120)))
        self.session.flush()

    def consume_first_order(self, installation: Installation, grant: ActivationGrant,
                            *, intent_fingerprint: str) -> None:
        self._assert_grant(installation, grant)
        now = self.clock()
        if grant.first_intent_consumed_at is not None:
            raise SafetyError("first_order_authorization_consumed")
        if grant.first_intent_expires_at is None or _aware(grant.first_intent_expires_at) <= _aware(now):
            raise SafetyError("first_order_authorization_expired")
        if grant.first_intent_hash != sha256(intent_fingerprint.encode("utf-8")).hexdigest():
            raise SafetyError("first_order_intent_mismatch")
        grant.first_intent_consumed_at = now
        grant.state = "first_order_used"
        self.session.flush()

    def reconcile_first_order(self, grant: ActivationGrant, *, authoritative: bool) -> None:
        if not authoritative or grant.state != "first_order_used":
            raise SafetyError("first_order_reconciliation_required")
        grant.first_intent_reconciled_at = self.clock()
        grant.state = "reviewed"
        self.session.flush()

    def approve_automated_sessions(self, installation: Installation, grant: ActivationGrant) -> None:
        if grant.state != "reviewed" or grant.first_intent_reconciled_at is None:
            raise SafetyError("first_order_review_required")
        grant.automated_sessions_approved_at = self.clock()
        self.transition(installation, "running", "first_order_review_approved")

    def _authorize_common(self, installation: Installation, binding: AccountBinding,
                          policy: PolicyVersion, consent: Consent) -> None:
        self._assert_binding(
            installation, binding, policy, policy.policy["strategy_version"],
            policy.policy["configuration_hash"],
        )
        if consent.revoked_at is not None or consent.account_binding_id != binding.id \
                or consent.policy_version_id != policy.id \
                or consent.credential_generation != binding.credential_generation:
            raise SafetyError("current_consent_required")
        if self.session.scalar(select(KillState).where(
            KillState.installation_id == installation.id, KillState.active.is_(True)
        )) is not None:
            raise SafetyError("active_kill")

    @staticmethod
    def _assert_binding(installation: Installation, binding: AccountBinding,
                        policy: PolicyVersion, strategy_version: str,
                        configuration_hash: str) -> None:
        if binding.installation_id != installation.id or not binding.is_active:
            raise SafetyError("active_exact_account_required")
        if policy.installation_id != installation.id or not policy.is_active:
            raise SafetyError("active_policy_required")
        if binding.provider_account_id not in policy.policy.get("allowed_account_ids", []):
            raise SafetyError("policy_account_mismatch")
        if policy.policy.get("strategy_version") != strategy_version \
                or policy.policy.get("configuration_hash") != configuration_hash:
            raise SafetyError("strategy_configuration_mismatch")

    def _assert_grant(self, installation: Installation, grant: ActivationGrant) -> None:
        now = self.clock()
        if grant.installation_id != installation.id or grant.state not in {"armed", "first_order_used"}:
            raise SafetyError("combine_arm_invalid")
        if grant.boot_id != self.boot_id:
            raise SafetyError("combine_arm_restart_invalidated")
        if _aware(grant.expires_at) <= _aware(now):
            grant.state = "expired"
            raise SafetyError("combine_arm_expired")
        policy = self.session.get(PolicyVersion, grant.policy_version_id)
        binding = self.session.get(AccountBinding, grant.account_binding_id)
        consent = self.session.get(Consent, grant.consent_id)
        self._authorize_common(installation, binding, policy, consent)

    def _invalidate_authorization(self, installation: Installation, reason: str) -> None:
        now = self.clock()
        for consent in self.session.scalars(select(Consent).where(
            Consent.installation_id == installation.id, Consent.revoked_at.is_(None)
        )):
            consent.revoked_at = now
        for evidence in self.session.scalars(select(QualificationEvidence).where(
            QualificationEvidence.installation_id == installation.id,
            QualificationEvidence.invalidated_at.is_(None),
        )):
            evidence.invalidated_at = now
        for grant in self.session.scalars(select(ActivationGrant).where(
            ActivationGrant.installation_id == installation.id,
            ActivationGrant.state.in_(("armed", "first_order_used")),
        )):
            grant.state = "invalidated"
            grant.invalidated_at = now
        if installation.lifecycle_state not in {"disabled", "observe_only"}:
            self.transition(installation, "observe_only", reason)

    def _invalidate_grants_and_consents(self, installation: Installation) -> None:
        now = self.clock()
        for consent in self.session.scalars(select(Consent).where(
            Consent.installation_id == installation.id, Consent.revoked_at.is_(None)
        )):
            consent.revoked_at = now
        for grant in self.session.scalars(select(ActivationGrant).where(
            ActivationGrant.installation_id == installation.id,
            ActivationGrant.state.in_(("armed", "first_order_used")),
        )):
            grant.state = "invalidated"
            grant.invalidated_at = now
