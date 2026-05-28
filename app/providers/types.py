from __future__ import annotations

from enum import Enum


class IntegrationProvider(str, Enum):
    TOPSTEPX = "TOPSTEPX"
    TRADOVATE = "TRADOVATE"
    NINJATRADER = "NINJATRADER"
    TRADINGVIEW = "TRADINGVIEW"
    IBKR = "IBKR"
    ETX = "ETX"


class IntegrationCapability(str, Enum):
    BROKER_TRADING = "BROKER_TRADING"
    MARKET_DATA = "MARKET_DATA"
    SIGNALS = "SIGNALS"
    ACCOUNT_INFO = "ACCOUNT_INFO"
    PAPER_TRADING = "PAPER_TRADING"


PROVIDER_CAPABILITIES: dict[IntegrationProvider, set[IntegrationCapability]] = {
    IntegrationProvider.TOPSTEPX: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
        IntegrationCapability.ACCOUNT_INFO,
    },
    IntegrationProvider.TRADOVATE: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
        IntegrationCapability.ACCOUNT_INFO,
    },
    IntegrationProvider.NINJATRADER: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
    },
    IntegrationProvider.IBKR: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
        IntegrationCapability.ACCOUNT_INFO,
    },
    IntegrationProvider.ETX: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
    },
    IntegrationProvider.TRADINGVIEW: {
        IntegrationCapability.SIGNALS,
    },
}


IMPLEMENTED_PROVIDER_CAPABILITIES: dict[IntegrationProvider, set[IntegrationCapability]] = {
    IntegrationProvider.TOPSTEPX: {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
        IntegrationCapability.ACCOUNT_INFO,
    },
    IntegrationProvider.TRADINGVIEW: {
        IntegrationCapability.SIGNALS,
    },
    IntegrationProvider.TRADOVATE: set(),
    IntegrationProvider.NINJATRADER: set(),
    IntegrationProvider.IBKR: set(),
    IntegrationProvider.ETX: set(),
}


ROADMAP_PROVIDER_CAPABILITIES: dict[IntegrationProvider, set[IntegrationCapability]] = {
    provider: PROVIDER_CAPABILITIES.get(provider, set())
    - IMPLEMENTED_PROVIDER_CAPABILITIES.get(provider, set())
    for provider in IntegrationProvider
}


def provider_supports(
    provider: IntegrationProvider,
    required_capabilities: set[IntegrationCapability] | None,
    *,
    implemented_only: bool = True,
) -> bool:
    capabilities = (
        IMPLEMENTED_PROVIDER_CAPABILITIES if implemented_only else PROVIDER_CAPABILITIES
    ).get(provider, set())
    return not required_capabilities or required_capabilities.issubset(capabilities)
