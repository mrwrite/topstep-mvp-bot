from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Any

from sqlalchemy.orm import Session

from app import database, models
from app.app_config import validate_config
from app.providers.types import IntegrationCapability
from app.trading_context import TradingContextError, trading_context_service


ACK_VERSION = "live-readiness-v1"
TERMS_VERSION = "terms-v1"


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _gate(code: str, passed: bool, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "passed": passed, "message": message, "details": details or {}}


def serialize_acknowledgement(ack: models.LiveReadinessAcknowledgement) -> dict[str, Any]:
    return {
        "id": ack.id,
        "user_id": ack.user_id,
        "integration_id": ack.integration_id,
        "account_id": ack.account_id,
        "symbol": ack.symbol,
        "risk_settings_id": ack.risk_settings_id,
        "acknowledgement_version": ack.acknowledgement_version,
        "terms_version": ack.terms_version,
        "acknowledgement_type": ack.acknowledgement_type,
        "accepted": bool(ack.accepted),
        "accepted_at": _utc_iso(ack.accepted_at),
        "expires_at": _utc_iso(ack.expires_at),
        "invalidated_at": _utc_iso(ack.invalidated_at),
        "metadata": ack.acknowledgement_metadata or {},
        "created_at": _utc_iso(ack.created_at),
    }


def serialize_launch_gate_evaluation(evaluation: models.LaunchGateEvaluation) -> dict[str, Any]:
    return {
        "id": evaluation.id,
        "user_id": evaluation.user_id,
        "integration_id": evaluation.integration_id,
        "account_id": evaluation.account_id,
        "symbol": evaluation.symbol,
        "all_required_gates_passed": bool(evaluation.all_required_gates_passed),
        "live_trading_available": bool(evaluation.live_trading_available),
        "live_feature_flag_enabled": bool(evaluation.live_feature_flag_enabled),
        "gate_results": evaluation.gate_results,
        "created_at": _utc_iso(evaluation.created_at),
    }


class LaunchGateService:
    def live_feature_flag_enabled(self) -> bool:
        return os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes"}

    def latest_acknowledgement(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None,
        account_id: str | None,
        symbol: str | None,
    ) -> models.LiveReadinessAcknowledgement | None:
        query = db.query(models.LiveReadinessAcknowledgement).filter(
            models.LiveReadinessAcknowledgement.user_id == user_id,
            models.LiveReadinessAcknowledgement.accepted == 1,
            models.LiveReadinessAcknowledgement.acknowledgement_version == ACK_VERSION,
            models.LiveReadinessAcknowledgement.terms_version == TERMS_VERSION,
            models.LiveReadinessAcknowledgement.invalidated_at.is_(None),
        )
        if integration_id is None:
            query = query.filter(models.LiveReadinessAcknowledgement.integration_id.is_(None))
        else:
            query = query.filter(models.LiveReadinessAcknowledgement.integration_id == integration_id)
        if account_id is None:
            query = query.filter(models.LiveReadinessAcknowledgement.account_id.is_(None))
        else:
            query = query.filter(models.LiveReadinessAcknowledgement.account_id == account_id)
        if symbol is None:
            query = query.filter(models.LiveReadinessAcknowledgement.symbol.is_(None))
        else:
            query = query.filter(models.LiveReadinessAcknowledgement.symbol == symbol)
        now = datetime.utcnow()
        return (
            query.filter(
                (models.LiveReadinessAcknowledgement.expires_at.is_(None))
                | (models.LiveReadinessAcknowledgement.expires_at > now)
            )
            .order_by(models.LiveReadinessAcknowledgement.accepted_at.desc())
            .first()
        )

    def create_acknowledgement(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None,
        account_id: str | None,
        symbol: str | None,
        risk_settings_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> models.LiveReadinessAcknowledgement:
        ack = models.LiveReadinessAcknowledgement(
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            symbol=symbol.upper() if symbol else None,
            risk_settings_id=risk_settings_id,
            acknowledgement_version=ACK_VERSION,
            terms_version=TERMS_VERSION,
            acknowledgement_type="live_risk",
            accepted=1,
            accepted_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
            acknowledgement_metadata=metadata
            or {
                "paper_only_currently": True,
                "no_profit_guarantee": True,
                "user_accepts_responsibility": True,
            },
        )
        db.add(ack)
        db.commit()
        db.refresh(ack)
        return ack

    def evaluate(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None,
        account_id: str | None,
        symbol: str | None,
        persist: bool = True,
    ) -> dict[str, Any]:
        normalized_symbol = symbol.upper() if symbol else None
        gates: list[dict[str, Any]] = []
        live_flag = self.live_feature_flag_enabled()
        gates.append(
            _gate(
                "global_live_disabled_by_default",
                not live_flag,
                "Live trading feature flag is disabled by default.",
                {"ENABLE_LIVE_TRADING": live_flag},
            )
        )

        context_integration_id = integration_id
        context_account_id = account_id
        try:
            context = trading_context_service.resolve(
                db,
                user_id=user_id,
                trading_mode="paper",
                integration_id=integration_id,
                account_id=account_id,
                symbol=normalized_symbol,
                required_capabilities={IntegrationCapability.PAPER_TRADING},
                require_integration=True,
                require_account=True,
                require_contract=True,
            )
            context_integration_id = context.integration_id
            context_account_id = context.account_id
            gates.append(_gate("trading_context_valid", True, "Selected integration, account, and contract context is valid."))
        except TradingContextError as exc:
            gates.append(_gate("trading_context_valid", False, exc.detail, {"blocker": exc.code}))

        risk_settings = None
        if context_integration_id is not None and context_account_id is not None:
            risk_settings = (
                db.query(models.RiskSettings)
                .filter(
                    models.RiskSettings.user_id == user_id,
                    models.RiskSettings.integration_id == context_integration_id,
                    models.RiskSettings.account_id == context_account_id,
                    models.RiskSettings.trading_mode == "paper",
                    models.RiskSettings.enabled == 1,
                )
                .order_by(models.RiskSettings.id.desc())
                .first()
            )
        gates.append(
            _gate(
                "risk_settings_exist",
                risk_settings is not None,
                "Persisted paper/live risk settings exist for this scope." if risk_settings else "Risk settings are missing for this scope.",
                {"risk_settings_id": risk_settings.id if risk_settings else None},
            )
        )

        active_kill_switch = (
            db.query(models.KillSwitch)
            .filter(models.KillSwitch.user_id == user_id, models.KillSwitch.active == 1)
            .first()
        )
        gates.append(
            _gate(
                "kill_switch_clear",
                active_kill_switch is None,
                "No active kill switch blocks this user." if active_kill_switch is None else "A kill switch is active.",
                {"kill_switch_id": active_kill_switch.id if active_kill_switch else None},
            )
        )

        paper_snapshot = None
        if context_integration_id is not None and context_account_id is not None:
            paper_snapshot = (
                db.query(models.PaperAccountSnapshot)
                .filter(
                    models.PaperAccountSnapshot.user_id == user_id,
                    models.PaperAccountSnapshot.integration_id == context_integration_id,
                    models.PaperAccountSnapshot.account_id == context_account_id,
                )
                .first()
            )
        gates.append(
            _gate(
                "paper_ledger_exists",
                paper_snapshot is not None,
                "Paper account ledger exists for this scope." if paper_snapshot else "Paper account ledger is missing for this scope.",
                {"snapshot_id": paper_snapshot.id if paper_snapshot else None},
            )
        )

        active_reconciliation_lock = (
            db.query(models.AccountReconciliationLock)
            .filter(models.AccountReconciliationLock.user_id == user_id, models.AccountReconciliationLock.active == 1)
            .first()
        )
        gates.append(
            _gate(
                "broker_reconciliation_clear",
                active_reconciliation_lock is None,
                "No unresolved reconciliation lock exists." if active_reconciliation_lock is None else active_reconciliation_lock.reason,
                {"lock_id": active_reconciliation_lock.id if active_reconciliation_lock else None},
            )
        )

        try:
            validate_config(database.APP_CONFIG)
            config_ok = True
            config_message = "Application configuration is valid."
        except Exception as exc:
            config_ok = False
            config_message = str(exc)
        gates.append(_gate("production_config_valid", config_ok, config_message, {"environment": database.APP_CONFIG.app_env}))

        ack = self.latest_acknowledgement(
            db,
            user_id=user_id,
            integration_id=context_integration_id,
            account_id=context_account_id,
            symbol=normalized_symbol,
        )
        ack_risk_matches = bool(ack and risk_settings and ack.risk_settings_id == risk_settings.id)
        gates.append(
            _gate(
                "legal_risk_acknowledgement_current",
                ack_risk_matches,
                "Current scoped legal/risk acknowledgement is recorded." if ack_risk_matches else "Current scoped legal/risk acknowledgement is missing.",
                {"acknowledgement_id": ack.id if ack else None, "risk_settings_id": risk_settings.id if risk_settings else None},
            )
        )

        all_required = all(gate["passed"] for gate in gates)
        live_available = bool(all_required and live_flag)
        evaluation = None
        if persist:
            evaluation = models.LaunchGateEvaluation(
                user_id=user_id,
                integration_id=context_integration_id,
                account_id=context_account_id,
                symbol=normalized_symbol,
                all_required_gates_passed=1 if all_required else 0,
                live_trading_available=1 if live_available else 0,
                live_feature_flag_enabled=1 if live_flag else 0,
                gate_results=gates,
            )
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)

        return {
            "evaluation_id": evaluation.id if evaluation else None,
            "all_required_gates_passed": all_required,
            "live_trading_available": live_available,
            "live_trading_blocked_reason": None if live_available else "Live trading remains disabled by feature flag and execution guards.",
            "live_feature_flag_enabled": live_flag,
            "acknowledgement_version": ACK_VERSION,
            "terms_version": TERMS_VERSION,
            "gates": gates,
        }


launch_gate_service = LaunchGateService()
