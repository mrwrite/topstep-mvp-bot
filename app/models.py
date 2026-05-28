from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text, Index, Float
from datetime import datetime
from .database import Base
from pydantic import BaseModel
from typing import Any, Optional
from .providers.types import IntegrationProvider

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    active_integration_id = Column(
        Integer,
        ForeignKey("platform_integrations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # User configurable trading rules
    buy_threshold = Column(Integer, default=30)
    sell_threshold = Column(Integer, default=70)


class PlatformIntegration(Base):
    __tablename__ = "platform_integrations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String, nullable=False)
    provider = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="active")
    integration_metadata = Column("metadata", JSON, nullable=True)
    credentials_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_platform_integrations_user_provider", "user_id", "provider"),
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    trading_mode = Column(String, nullable=False, default="paper")
    order_type = Column(String, nullable=False, default="market")
    source = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default="submitted", index=True)
    provider_order_id = Column(String, nullable=True, index=True)
    response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_paper_orders_user_idempotency", "user_id", "idempotency_key", unique=True),
        Index("ix_paper_orders_user_status", "user_id", "status"),
    )


class PaperOrderEvent(Base):
    __tablename__ = "paper_order_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    event_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_paper_positions_scope", "user_id", "integration_id", "account_id", "symbol", unique=True),
    )


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserPublic(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class TradingRuleUpdate(BaseModel):
    buy_threshold: int
    sell_threshold: int


class IntegrationBase(BaseModel):
    display_name: str
    provider: IntegrationProvider
    metadata: Optional[dict[str, Any]] = None
    status: Optional[str] = "active"


class IntegrationCreate(IntegrationBase):
    credentials: Optional[dict[str, Any]] = None


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    credentials: Optional[dict[str, Any]] = None


class IntegrationOut(BaseModel):
    id: int
    display_name: str
    provider: IntegrationProvider
    status: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    has_credentials: bool

    class Config:
        orm_mode = True
