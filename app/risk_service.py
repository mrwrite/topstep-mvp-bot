from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.trading_safety import LIVE_MODE, PAPER_MODE, OrderIntent
from app.time_utils import utc_now


DEFAULT_MAX_QUANTITY = 1
DEFAULT_MAX_CONTRACTS = 1
DEFAULT_MAX_DAILY_LOSS = 0.0
DEFAULT_MAX_OPEN_POSITIONS = 1


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _scope_filter(query, model, *, user_id: int, integration_id: int | None, account_id: str | None, trading_mode: str):
    query = query.filter(model.user_id == user_id, model.trading_mode == trading_mode)
    if integration_id is None:
        query = query.filter(model.integration_id.is_(None))
    else:
        query = query.filter(model.integration_id == integration_id)
    if account_id is None:
        query = query.filter(model.account_id.is_(None))
    else:
        query = query.filter(model.account_id == account_id)
    return query


def serialize_risk_settings(settings: models.RiskSettings) -> dict[str, Any]:
    return {
        "id": settings.id,
        "user_id": settings.user_id,
        "integration_id": settings.integration_id,
        "account_id": settings.account_id,
        "trading_mode": settings.trading_mode,
        "enabled": bool(settings.enabled),
        "max_quantity": settings.max_quantity,
        "max_contracts": settings.max_contracts,
        "max_daily_loss": settings.max_daily_loss,
        "max_open_positions": settings.max_open_positions,
        "live_trading_enabled": bool(settings.live_trading_enabled),
        "reset_policy": settings.reset_policy,
        "effective_at": _utc_iso(settings.effective_at),
        "created_at": _utc_iso(settings.created_at),
        "updated_at": _utc_iso(settings.updated_at),
    }


def serialize_kill_switch(kill_switch: models.KillSwitch) -> dict[str, Any]:
    return {
        "id": kill_switch.id,
        "user_id": kill_switch.user_id,
        "integration_id": kill_switch.integration_id,
        "account_id": kill_switch.account_id,
        "bot_session_id": kill_switch.bot_session_id,
        "active": bool(kill_switch.active),
        "reason": kill_switch.reason,
        "activated_by_user_id": kill_switch.activated_by_user_id,
        "deactivated_by_user_id": kill_switch.deactivated_by_user_id,
        "activated_at": _utc_iso(kill_switch.activated_at),
        "deactivated_at": _utc_iso(kill_switch.deactivated_at),
        "created_at": _utc_iso(kill_switch.created_at),
    }


def serialize_risk_decision(decision: models.RiskDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "user_id": decision.user_id,
        "risk_settings_id": decision.risk_settings_id,
        "kill_switch_id": decision.kill_switch_id,
        "paper_order_id": decision.paper_order_id,
        "integration_id": decision.integration_id,
        "account_id": decision.account_id,
        "symbol": decision.symbol,
        "side": decision.side,
        "quantity": decision.quantity,
        "trading_mode": decision.trading_mode,
        "source": decision.source,
        "allowed": bool(decision.allowed),
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "metadata": decision.decision_metadata or {},
        "created_at": _utc_iso(decision.created_at),
    }


class RiskService:
    def get_or_create_settings(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None = None,
        account_id: str | None = None,
        trading_mode: str = PAPER_MODE,
    ) -> models.RiskSettings:
        query = _scope_filter(
            db.query(models.RiskSettings),
            models.RiskSettings,
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            trading_mode=trading_mode,
        )
        settings = query.order_by(models.RiskSettings.id.desc()).first()
        if settings:
            return settings

        settings = models.RiskSettings(
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            trading_mode=trading_mode,
            enabled=1,
            max_quantity=DEFAULT_MAX_QUANTITY,
            max_contracts=DEFAULT_MAX_CONTRACTS,
            max_daily_loss=DEFAULT_MAX_DAILY_LOSS,
            max_open_positions=DEFAULT_MAX_OPEN_POSITIONS,
            live_trading_enabled=0,
            reset_policy="daily",
            effective_at=utc_now(),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(settings)
        db.flush()
        return settings

    def resolve_settings_for_intent(self, db: Session, intent: OrderIntent) -> models.RiskSettings:
        if intent.integration_id is not None or intent.account_id is not None:
            scoped = _scope_filter(
                db.query(models.RiskSettings),
                models.RiskSettings,
                user_id=intent.user_id,
                integration_id=intent.integration_id,
                account_id=intent.account_id,
                trading_mode=intent.trading_mode,
            ).order_by(models.RiskSettings.id.desc()).first()
            if scoped:
                return scoped
        return self.get_or_create_settings(db, user_id=intent.user_id, trading_mode=intent.trading_mode)

    def update_settings(
        self,
        db: Session,
        *,
        user_id: int,
        max_quantity: int,
        max_contracts: int,
        max_daily_loss: float,
        max_open_positions: int,
        integration_id: int | None = None,
        account_id: str | None = None,
        trading_mode: str = PAPER_MODE,
    ) -> models.RiskSettings:
        settings = self.get_or_create_settings(
            db,
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            trading_mode=trading_mode,
        )
        settings.max_quantity = max_quantity
        settings.max_contracts = max_contracts
        settings.max_daily_loss = max_daily_loss
        settings.max_open_positions = max_open_positions
        settings.live_trading_enabled = 0
        settings.enabled = 1
        settings.updated_at = utc_now()
        db.commit()
        db.refresh(settings)
        return settings

    def _switch_matches(
        self,
        kill_switch: models.KillSwitch,
        *,
        integration_id: int | None,
        account_id: str | None,
        bot_session_id: str | None = None,
    ) -> bool:
        if kill_switch.bot_session_id and kill_switch.bot_session_id != bot_session_id:
            return False
        if kill_switch.integration_id is not None and kill_switch.integration_id != integration_id:
            return False
        if kill_switch.account_id is not None and kill_switch.account_id != account_id:
            return False
        return True

    def find_active_kill_switch(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None = None,
        account_id: str | None = None,
        bot_session_id: str | None = None,
    ) -> models.KillSwitch | None:
        candidates = (
            db.query(models.KillSwitch)
            .filter(models.KillSwitch.user_id == user_id, models.KillSwitch.active == 1)
            .order_by(models.KillSwitch.activated_at.desc())
            .all()
        )
        for candidate in candidates:
            if self._switch_matches(
                candidate,
                integration_id=integration_id,
                account_id=account_id,
                bot_session_id=bot_session_id,
            ):
                return candidate
        return None

    def activate_kill_switch(
        self,
        db: Session,
        *,
        user_id: int,
        actor_user_id: int,
        reason: str | None = None,
        integration_id: int | None = None,
        account_id: str | None = None,
        bot_session_id: str | None = None,
    ) -> models.KillSwitch:
        kill_switch = models.KillSwitch(
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            bot_session_id=bot_session_id,
            active=1,
            reason=reason or "User activated kill switch.",
            activated_by_user_id=actor_user_id,
            activated_at=utc_now(),
            created_at=utc_now(),
        )
        db.add(kill_switch)
        db.flush()
        db.add(
            models.RiskLockoutEvent(
                user_id=user_id,
                kill_switch_id=kill_switch.id,
                integration_id=integration_id,
                account_id=account_id,
                trading_mode=PAPER_MODE,
                reason=kill_switch.reason or "Kill switch active.",
                active=1,
            )
        )
        return kill_switch

    def deactivate_kill_switch(
        self,
        db: Session,
        *,
        user_id: int,
        switch_id: int,
        actor_user_id: int,
    ) -> models.KillSwitch:
        kill_switch = (
            db.query(models.KillSwitch)
            .filter(models.KillSwitch.id == switch_id, models.KillSwitch.user_id == user_id)
            .first()
        )
        if not kill_switch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kill switch not found.")
        kill_switch.active = 0
        kill_switch.deactivated_by_user_id = actor_user_id
        kill_switch.deactivated_at = utc_now()
        (
            db.query(models.RiskLockoutEvent)
            .filter(models.RiskLockoutEvent.kill_switch_id == kill_switch.id, models.RiskLockoutEvent.active == 1)
            .update({"active": 0, "cleared_at": utc_now()})
        )
        db.commit()
        db.refresh(kill_switch)
        return kill_switch

    def assert_no_active_kill_switch(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None = None,
        account_id: str | None = None,
        bot_session_id: str | None = None,
    ) -> None:
        kill_switch = self.find_active_kill_switch(
            db,
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            bot_session_id=bot_session_id,
        )
        if kill_switch:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=kill_switch.reason or "Kill switch is active for this trading scope.",
                headers={"X-Readiness-Blocker": "kill_switch_active"},
            )

    def evaluate_order_intent(
        self,
        db: Session,
        intent: OrderIntent,
        *,
        commit_on_reject: bool = True,
        simulation_run_id: str | None = None,
        simulation_fencing_token: int | None = None,
        evaluation_identity: str | None = None,
    ) -> models.RiskDecision:
        settings = self.resolve_settings_for_intent(db, intent)
        allowed = True
        reason_code = "allowed"
        reason = "Order intent passed persisted risk checks."
        metadata: dict[str, Any] = {
            "max_quantity": settings.max_quantity,
            "max_contracts": settings.max_contracts,
            "max_daily_loss": settings.max_daily_loss,
            "max_open_positions": settings.max_open_positions,
            "live_trading_enabled": bool(settings.live_trading_enabled),
        }
        snapshot_query = db.query(models.PaperAccountSnapshot).filter(models.PaperAccountSnapshot.user_id == intent.user_id)
        if intent.integration_id is None:
            snapshot_query = snapshot_query.filter(models.PaperAccountSnapshot.integration_id.is_(None))
        else:
            snapshot_query = snapshot_query.filter(models.PaperAccountSnapshot.integration_id == intent.integration_id)
        if intent.account_id is None:
            snapshot_query = snapshot_query.filter(models.PaperAccountSnapshot.account_id.is_(None))
        else:
            snapshot_query = snapshot_query.filter(models.PaperAccountSnapshot.account_id == intent.account_id)
        snapshot = snapshot_query.order_by(models.PaperAccountSnapshot.updated_at.desc()).first()
        if snapshot:
            metadata["paper_account"] = {
                "snapshot_id": snapshot.id,
                "cash_balance": snapshot.cash_balance,
                "equity": snapshot.equity,
                "buying_power": snapshot.buying_power,
                "realized_pnl": snapshot.realized_pnl,
                "unrealized_pnl": snapshot.unrealized_pnl,
            }

        kill_switch = self.find_active_kill_switch(
            db,
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
        )
        reconciliation_lock = (
            db.query(models.AccountReconciliationLock)
            .filter(models.AccountReconciliationLock.user_id == intent.user_id, models.AccountReconciliationLock.active == 1)
        )
        if intent.integration_id is None:
            reconciliation_lock = reconciliation_lock.filter(models.AccountReconciliationLock.integration_id.is_(None))
        else:
            reconciliation_lock = reconciliation_lock.filter(models.AccountReconciliationLock.integration_id == intent.integration_id)
        if intent.account_id is None:
            reconciliation_lock = reconciliation_lock.filter(models.AccountReconciliationLock.account_id.is_(None))
        else:
            reconciliation_lock = reconciliation_lock.filter(models.AccountReconciliationLock.account_id == intent.account_id)
        active_reconciliation_lock = reconciliation_lock.first()

        if intent.trading_mode == LIVE_MODE:
            allowed = False
            reason_code = "live_disabled"
            reason = "Live trading remains disabled until launch gates are complete."
            metadata["account_equity_required"] = True
            metadata["account_equity_available"] = False
        elif not settings.enabled:
            allowed = False
            reason_code = "risk_settings_inactive"
            reason = "Risk settings are inactive for this trading scope."
        elif kill_switch:
            allowed = False
            reason_code = "kill_switch_active"
            reason = kill_switch.reason or "Kill switch is active for this trading scope."
        elif active_reconciliation_lock:
            allowed = False
            reason_code = "reconciliation_required"
            reason = active_reconciliation_lock.reason
        elif intent.quantity > settings.max_quantity:
            allowed = False
            reason_code = "max_quantity_exceeded"
            reason = f"Order quantity {intent.quantity} exceeds max quantity {settings.max_quantity}."
        elif intent.quantity > settings.max_contracts:
            allowed = False
            reason_code = "max_contracts_exceeded"
            reason = f"Order quantity {intent.quantity} exceeds max contracts {settings.max_contracts}."
        else:
            open_positions = (
                db.query(models.PaperPosition)
                .filter(
                    models.PaperPosition.user_id == intent.user_id,
                    models.PaperPosition.quantity != 0,
                )
            )
            if intent.integration_id is None:
                open_positions = open_positions.filter(models.PaperPosition.integration_id.is_(None))
            else:
                open_positions = open_positions.filter(models.PaperPosition.integration_id == intent.integration_id)
            if intent.account_id is None:
                open_positions = open_positions.filter(models.PaperPosition.account_id.is_(None))
            else:
                open_positions = open_positions.filter(models.PaperPosition.account_id == intent.account_id)
            open_symbols = {position.symbol for position in open_positions.all()}
            metadata["open_position_count"] = len(open_symbols)
            if intent.symbol not in open_symbols and len(open_symbols) >= settings.max_open_positions:
                allowed = False
                reason_code = "max_open_positions_exceeded"
                reason = f"Open position count {len(open_symbols)} meets max open positions {settings.max_open_positions}."

        if allowed:
            today = utc_now().date().isoformat()
            daily_state = _scope_filter(
                db.query(models.DailyRiskState),
                models.DailyRiskState,
                user_id=intent.user_id,
                integration_id=intent.integration_id,
                account_id=intent.account_id,
                trading_mode=intent.trading_mode,
            ).filter(models.DailyRiskState.trading_day == today).first()
            if daily_state and daily_state.locked:
                allowed = False
                reason_code = "daily_risk_lockout"
                reason = daily_state.lock_reason or "Daily risk state is locked."
            elif daily_state and settings.max_daily_loss > 0 and daily_state.realized_pnl <= -settings.max_daily_loss:
                allowed = False
                reason_code = "max_daily_loss_exceeded"
                reason = "Daily loss limit has been reached."

        decision = models.RiskDecision(
            user_id=intent.user_id,
            risk_settings_id=settings.id,
            kill_switch_id=kill_switch.id if kill_switch else None,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            trading_mode=intent.trading_mode,
            source=intent.source,
            allowed=1 if allowed else 0,
            reason_code=reason_code,
            reason=reason,
            decision_metadata=metadata,
            simulation_run_id=simulation_run_id,
            simulation_fencing_token=simulation_fencing_token,
            evaluation_identity=evaluation_identity,
        )
        db.add(decision)
        db.flush()
        if not allowed:
            if commit_on_reject:
                db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason,
                headers={"X-Readiness-Blocker": reason_code},
            )
        return decision


risk_service = RiskService()
