from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.crypto import encrypt_credentials
from app.observability import log_event
from app.paper_execution import execute_paper_order
from app.risk_service import risk_service
from app.strategy import STRATEGY_NAME, STRATEGY_VERSION
from app.strategy_engine import create_strategy_config
from app.trading_safety import build_order_intent


router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_ACCOUNT_ID = "DEMO-PAPER-001"
DEMO_CONTRACTS = ["ES", "NQ", "YM"]
DEMO_BOT_SESSION_ID = "demo-package"


def _is_demo_integration(integration: models.PlatformIntegration) -> bool:
    metadata = integration.integration_metadata or {}
    return bool(metadata.get("demo_seed"))


def _demo_integration_ids(db: Session, user_id: int) -> list[int]:
    integrations = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.user_id == user_id)
        .all()
    )
    return [integration.id for integration in integrations if _is_demo_integration(integration)]


def _delete_demo_data(db: Session, user_id: int) -> dict[str, int]:
    integration_ids = _demo_integration_ids(db, user_id)
    demo_orders = (
        db.query(models.PaperOrder)
        .filter(models.PaperOrder.user_id == user_id)
        .filter(models.PaperOrder.idempotency_key.like("demo:%"))
        .all()
    )
    demo_order_ids = [order.id for order in demo_orders]
    if demo_order_ids:
        db.query(models.PaperLedgerEntry).filter(models.PaperLedgerEntry.paper_order_id.in_(demo_order_ids)).delete(
            synchronize_session=False
        )
        db.query(models.PaperFill).filter(models.PaperFill.order_id.in_(demo_order_ids)).delete(
            synchronize_session=False
        )
        db.query(models.PaperOrderEvent).filter(models.PaperOrderEvent.order_id.in_(demo_order_ids)).delete(
            synchronize_session=False
        )
        db.query(models.PaperOrder).filter(models.PaperOrder.id.in_(demo_order_ids)).delete(
            synchronize_session=False
        )

    demo_configs = (
        db.query(models.StrategyConfig)
        .filter(
            models.StrategyConfig.user_id == user_id,
            models.StrategyConfig.bot_session_id == DEMO_BOT_SESSION_ID,
        )
        .all()
    )
    demo_config_ids = [config.id for config in demo_configs]
    if demo_config_ids:
        db.query(models.StrategySignal).filter(
            models.StrategySignal.strategy_config_id.in_(demo_config_ids)
        ).delete(synchronize_session=False)
        db.query(models.StrategyConfig).filter(models.StrategyConfig.id.in_(demo_config_ids)).delete(
            synchronize_session=False
        )

    db.query(models.PaperPosition).filter(
        models.PaperPosition.user_id == user_id,
        models.PaperPosition.account_id == DEMO_ACCOUNT_ID,
    ).delete(synchronize_session=False)
    db.query(models.PaperAccountSnapshot).filter(
        models.PaperAccountSnapshot.user_id == user_id,
        models.PaperAccountSnapshot.account_id == DEMO_ACCOUNT_ID,
    ).delete(synchronize_session=False)

    if integration_ids:
        db.query(models.RiskDecision).filter(
            models.RiskDecision.user_id == user_id,
            models.RiskDecision.integration_id.in_(integration_ids),
        ).delete(synchronize_session=False)
        db.query(models.RiskSettings).filter(
            models.RiskSettings.user_id == user_id,
            models.RiskSettings.integration_id.in_(integration_ids),
        ).delete(synchronize_session=False)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user and user.active_integration_id in integration_ids:
            user.active_integration_id = None
        db.query(models.PlatformIntegration).filter(models.PlatformIntegration.id.in_(integration_ids)).delete(
            synchronize_session=False
        )

    db.commit()
    return {
        "integrations": len(integration_ids),
        "orders": len(demo_order_ids),
        "strategy_configs": len(demo_config_ids),
    }


def _demo_checklist(*, seeded: bool, orders: int, positions: int, signals: int) -> list[dict[str, Any]]:
    return [
        {
            "label": "Execution mode",
            "status": "ready",
            "detail": "Paper-only demo mode. Live broker execution is disabled.",
        },
        {
            "label": "Demo integration",
            "status": "ready" if seeded else "missing",
            "detail": "Seeded demo integration uses fake credentials and cannot route live orders.",
        },
        {
            "label": "Demo account",
            "status": "ready" if seeded else "missing",
            "detail": DEMO_ACCOUNT_ID,
        },
        {
            "label": "Paper order history",
            "status": "ready" if orders else "empty",
            "detail": f"{orders} seeded paper orders.",
        },
        {
            "label": "Paper positions",
            "status": "ready" if positions else "empty",
            "detail": f"{positions} seeded positions.",
        },
        {
            "label": "Strategy signals",
            "status": "ready" if signals else "empty",
            "detail": f"{signals} seeded strategy signals.",
        },
        {
            "label": "Consumer readiness",
            "status": "blocked",
            "detail": "Live readiness still requires unresolved risk, execution, UX, and legal work.",
        },
    ]


def _demo_status(db: Session, user_id: int) -> dict[str, Any]:
    integration_ids = _demo_integration_ids(db, user_id)
    order_count = (
        db.query(models.PaperOrder)
        .filter(models.PaperOrder.user_id == user_id, models.PaperOrder.idempotency_key.like("demo:%"))
        .count()
    )
    position_count = (
        db.query(models.PaperPosition)
        .filter(models.PaperPosition.user_id == user_id, models.PaperPosition.account_id == DEMO_ACCOUNT_ID)
        .count()
    )
    signal_count = (
        db.query(models.StrategySignal)
        .filter(models.StrategySignal.user_id == user_id)
        .join(models.StrategyConfig, models.StrategySignal.strategy_config_id == models.StrategyConfig.id)
        .filter(models.StrategyConfig.bot_session_id == DEMO_BOT_SESSION_ID)
        .count()
    )
    seeded = bool(integration_ids)
    return {
        "demo_mode": True,
        "seeded": seeded,
        "paper_only": True,
        "live_trading_enabled": False,
        "demo_account_id": DEMO_ACCOUNT_ID if seeded else None,
        "demo_contracts": DEMO_CONTRACTS,
        "counts": {
            "integrations": len(integration_ids),
            "paper_orders": order_count,
            "paper_positions": position_count,
            "strategy_signals": signal_count,
        },
        "checklist": _demo_checklist(
            seeded=seeded,
            orders=order_count,
            positions=position_count,
            signals=signal_count,
        ),
        "disclaimer": (
            "Demo mode uses paper-only data and simulated fills. It does not place live broker "
            "orders and does not imply future trading performance."
        ),
        "remaining_blockers": [
            "Full risk-settings schema and kill switch records remain incomplete.",
            "Live order reconciliation, partial fills, retries, and provider status polling remain incomplete.",
            "Terms, privacy policy, and legal review are placeholders.",
            "Provider expansion remains roadmap-only outside implemented TopStepX/TradingView capabilities.",
        ],
    }


@router.get("/status")
def demo_status(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return _demo_status(db, current_user.id)


@router.post("/seed")
def seed_demo_package(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    _delete_demo_data(db, current_user.id)

    integration = models.PlatformIntegration(
        user_id=current_user.id,
        display_name="Demo Paper Broker",
        provider="TOPSTEPX",
        status="active",
        integration_metadata={
            "demo_seed": True,
            "environment": "demo",
            "account_id": DEMO_ACCOUNT_ID,
            "contracts": DEMO_CONTRACTS,
            "live_trading_enabled": False,
        },
        credentials_encrypted=None,
    )
    db.add(integration)
    db.flush()
    integration.credentials_encrypted = encrypt_credentials(
        {
            "userName": "demo-paper-user",
            "apiKey": "demo-paper-key-not-live",
            "baseUrl": "https://demo.invalid",
        },
        user_id=current_user.id,
        record_id=integration.id,
    )

    current_user.active_integration_id = integration.id
    db.flush()
    risk_service.update_settings(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=DEMO_ACCOUNT_ID,
        trading_mode="paper",
        max_quantity=1,
        max_contracts=1,
        max_daily_loss=0,
        max_open_positions=len(DEMO_CONTRACTS),
    )

    order_one = execute_paper_order(
        db,
        build_order_intent(
            user_id=current_user.id,
            symbol="ES",
            side="BUY",
            quantity=1,
            trading_mode="paper",
            integration_id=integration.id,
            account_id=DEMO_ACCOUNT_ID,
            idempotency_key="demo:paper-order-1",
            source="demo",
            reference_price=5325.25,
        ),
    )
    order_two = execute_paper_order(
        db,
        build_order_intent(
            user_id=current_user.id,
            symbol="NQ",
            side="SELL",
            quantity=1,
            trading_mode="paper",
            integration_id=integration.id,
            account_id=DEMO_ACCOUNT_ID,
            idempotency_key="demo:paper-order-2",
            source="demo",
            reference_price=18750.5,
        ),
    )

    strategy_config = create_strategy_config(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=DEMO_ACCOUNT_ID,
        symbol="ES",
        trading_mode="paper",
        parameters={"buy_threshold": 30, "sell_threshold": 70, "max_signals_per_hour": 4},
        bot_session_id=DEMO_BOT_SESSION_ID,
    )
    signal = models.StrategySignal(
        user_id=current_user.id,
        strategy_config_id=strategy_config.id,
        paper_order_id=order_one["order"]["id"],
        integration_id=integration.id,
        account_id=DEMO_ACCOUNT_ID,
        symbol="ES",
        signal="BUY",
        status="executed",
        reason="demo_seed",
        guardrail_decision={"allowed": True, "reason": "demo_seed"},
        market_snapshot={"close": 5325.25, "rsi": 28.4},
        created_at=datetime.utcnow(),
    )
    db.add(signal)
    db.commit()

    log_event(
        "demo",
        "demo_package_seeded",
        user_id=current_user.id,
        integration_id=integration.id,
        paper_order_ids=[order_one["order"]["id"], order_two["order"]["id"]],
        strategy_config_id=strategy_config.id,
        live=False,
    )
    return _demo_status(db, current_user.id)


@router.post("/reset")
def reset_demo_package(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    deleted = _delete_demo_data(db, current_user.id)
    log_event("demo", "demo_package_reset", user_id=current_user.id, deleted=deleted, live=False)
    return {"status": "reset", "deleted": deleted, **_demo_status(db, current_user.id)}
