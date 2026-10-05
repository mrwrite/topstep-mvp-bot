from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any, Callable

import requests

from .credentials import TopstepCredentials
from .rate_budget import DurableRateLimiter
from .session import SessionToken


class LocalProviderError(RuntimeError):
    def __init__(
        self,
        classification: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        provider_error_code: int | None = None,
    ) -> None:
        super().__init__(classification)
        self.classification = classification
        self.retryable = retryable
        self.http_status = http_status
        self.provider_error_code = provider_error_code

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "provider_error_code": self.provider_error_code,
        }


@dataclass(frozen=True)
class LocalAccount:
    id: int
    can_trade: bool
    is_visible: bool


@dataclass(frozen=True)
class LocalContract:
    id: str
    name: str
    symbol_id: str | None
    tick_size: str
    tick_value: str
    active: bool


@dataclass(frozen=True)
class LocalBar:
    timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: int


@dataclass(frozen=True)
class LocalOrder:
    id: int
    account_id: int
    contract_id: str
    status: int
    order_type: int
    side: int
    size: int
    limit_price: str | None
    stop_price: str | None
    trail_price: str | None
    custom_tag: str | None
    creation_timestamp: str


@dataclass(frozen=True)
class LocalTrade:
    id: int
    account_id: int
    order_id: int
    contract_id: str
    side: int
    size: int
    price: str
    profit_and_loss: str | None
    creation_timestamp: str
    voided: bool


@dataclass(frozen=True)
class LocalPosition:
    id: int
    account_id: int
    contract_id: str
    side_type: int
    size: int
    average_price: str
    creation_timestamp: str


@dataclass(frozen=True)
class MutationResult:
    classification: str
    provider_error_code: int
    provider_order_id: int | None = None


ORDER_TYPES = {
    "limit": 1,
    "market": 2,
    "stop": 4,
    "trailing_stop": 5,
    "join_bid": 6,
    "join_ask": 7,
}
ORDER_SIDES = {"BUY": 0, "SELL": 1}


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LocalProviderError(f"malformed_{field}")
    return value


def _string(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise LocalProviderError(f"malformed_{field}")
    return value


def _decimal_string(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise LocalProviderError(f"malformed_{field}")
    return str(value)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return value.astimezone(timezone.utc).isoformat()


class LocalTopstepClient:
    """Personal-device Topstep client; mutations use a non-retrying code path."""

    def __init__(
        self,
        rate_limiter: DurableRateLimiter,
        *,
        base_url: str = "https://api.topstepx.com",
        http_session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        read_retries: int = 1,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._base_url = base_url.rstrip("/")
        self._http = http_session or requests.Session()
        self._sleep = sleep
        self._read_retries = max(0, min(read_retries, 2))
        self._clock_skew_seconds: float | None = None

    @property
    def clock_skew_seconds(self) -> float | None:
        return self._clock_skew_seconds

    def _observe_server_date(self, response: Any) -> None:
        value = response.headers.get("Date")
        if not isinstance(value, str) or not value:
            return
        try:
            server_time = parsedate_to_datetime(value)
            if server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
            self._clock_skew_seconds = (
                server_time.astimezone(timezone.utc) - datetime.now(timezone.utc)
            ).total_seconds()
        except (TypeError, ValueError, OverflowError):
            self._clock_skew_seconds = None

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None = None,
        bucket: str = "general",
    ) -> dict[str, Any]:
        headers = {"accept": "text/plain", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        last_error: LocalProviderError | None = None
        for attempt in range(self._read_retries + 1):
            self._rate_limiter.acquire(bucket)
            try:
                response = self._http.post(
                    f"{self._base_url}{path}", headers=headers, json=payload, timeout=20
                )
            except requests.RequestException:
                last_error = LocalProviderError("provider_transport_error", retryable=True)
                if attempt < self._read_retries:
                    self._sleep(0.1 * (attempt + 1))
                    continue
                raise last_error from None
            status = int(response.status_code)
            self._observe_server_date(response)
            if status == 429:
                try:
                    retry_after = int(response.headers.get("Retry-After", "30"))
                except (TypeError, ValueError):
                    retry_after = 30
                self._rate_limiter.record_provider_429(bucket, retry_after)
                raise LocalProviderError("provider_rate_limited", retryable=True, http_status=429)
            if status == 401:
                raise LocalProviderError("provider_unauthorized", http_status=401)
            if status >= 500:
                last_error = LocalProviderError(
                    "provider_unavailable", retryable=True, http_status=status
                )
                if attempt < self._read_retries:
                    self._sleep(0.1 * (attempt + 1))
                    continue
                raise last_error
            if status < 200 or status >= 300:
                raise LocalProviderError("provider_http_error", http_status=status)
            try:
                data = response.json()
            except (ValueError, TypeError):
                raise LocalProviderError("provider_malformed_json") from None
            if not isinstance(data, dict):
                raise LocalProviderError("provider_malformed_response")
            if data.get("success") is not True or data.get("errorCode", 0) != 0:
                error_code = data.get("errorCode")
                raise LocalProviderError(
                    "provider_rejected",
                    provider_error_code=error_code if isinstance(error_code, int) else None,
                )
            return data
        raise last_error or LocalProviderError("provider_unavailable")

    def _mutate(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str,
        pending_codes: frozenset[int],
        unknown_codes: frozenset[int],
    ) -> MutationResult:
        """Perform exactly one provider call; callers must reconcile any ambiguity."""
        self._rate_limiter.acquire("general")
        headers = {
            "accept": "text/plain",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            response = self._http.post(
                f"{self._base_url}{path}", headers=headers, json=payload, timeout=20
            )
        except requests.Timeout:
            raise LocalProviderError("provider_mutation_timeout") from None
        except requests.RequestException:
            raise LocalProviderError("provider_mutation_transport_lost") from None
        status = int(response.status_code)
        self._observe_server_date(response)
        if status == 429:
            try:
                retry_after = int(response.headers.get("Retry-After", "30"))
            except (TypeError, ValueError):
                retry_after = 30
            self._rate_limiter.record_provider_429("general", retry_after)
            return MutationResult("rate_limited", 429)
        if status == 401:
            return MutationResult("unauthorized", 401)
        if status < 200 or status >= 300:
            # Once a mutation request is transmitted, an HTTP failure is not proof that
            # the trading engine did not act. Reconciliation, never retry, decides.
            raise LocalProviderError("provider_mutation_http_ambiguous", http_status=status)
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise LocalProviderError("provider_mutation_malformed_json") from None
        if not isinstance(data, dict):
            raise LocalProviderError("provider_mutation_malformed_response")
        code = data.get("errorCode")
        if isinstance(code, bool) or not isinstance(code, int):
            raise LocalProviderError("provider_mutation_malformed_response")
        order_id = data.get("orderId")
        if order_id is not None and (isinstance(order_id, bool) or not isinstance(order_id, int)):
            raise LocalProviderError("provider_mutation_malformed_response")
        if data.get("success") is True and code == 0:
            return MutationResult("accepted", code, order_id)
        if code in pending_codes:
            return MutationResult("pending", code, order_id)
        if code in unknown_codes:
            return MutationResult("unknown", code, order_id)
        return MutationResult("rejected", code, order_id)

    def place_order(
        self,
        token: str,
        *,
        account_id: int,
        contract_id: str,
        order_type: str,
        side: str,
        quantity: int,
        custom_tag: str,
        limit_price: str | float | None = None,
        stop_price: str | float | None = None,
        trail_price: str | float | None = None,
    ) -> MutationResult:
        if quantity != 1:
            raise ValueError("quantity_must_equal_one")
        if order_type not in ORDER_TYPES:
            raise ValueError("unsupported_order_type")
        if side not in ORDER_SIDES:
            raise ValueError("unsupported_order_side")
        if not custom_tag or len(custom_tag) > 64:
            raise ValueError("invalid_custom_tag")
        if order_type == "trailing_stop" and trail_price is None:
            raise ValueError("trailing_stop_price_required")
        return self._mutate(
            "/api/Order/place",
            {
                "accountId": account_id,
                "contractId": contract_id,
                "type": ORDER_TYPES[order_type],
                "side": ORDER_SIDES[side],
                "size": 1,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
                "trailPrice": trail_price,
                "customTag": custom_tag,
                "stopLossBracket": None,
                "takeProfitBracket": None,
            },
            token=token,
            pending_codes=frozenset({6}),
            unknown_codes=frozenset({7}),
        )

    def cancel_order(self, token: str, *, account_id: int, order_id: int) -> MutationResult:
        return self._mutate(
            "/api/Order/cancel", {"accountId": account_id, "orderId": order_id},
            token=token, pending_codes=frozenset({4}), unknown_codes=frozenset({5}),
        )

    def modify_order(
        self,
        token: str,
        *,
        account_id: int,
        order_id: int,
        quantity: int | None = None,
        limit_price: str | float | None = None,
        stop_price: str | float | None = None,
        trail_price: str | float | None = None,
    ) -> MutationResult:
        if quantity not in (None, 1):
            raise ValueError("quantity_must_equal_one")
        return self._mutate(
            "/api/Order/modify",
            {"accountId": account_id, "orderId": order_id, "size": quantity,
             "limitPrice": limit_price, "stopPrice": stop_price, "trailPrice": trail_price},
            token=token, pending_codes=frozenset({4}), unknown_codes=frozenset({5}),
        )

    def close_position(
        self, token: str, *, account_id: int, contract_id: str
    ) -> MutationResult:
        return self._mutate(
            "/api/Position/closeContract",
            {"accountId": account_id, "contractId": contract_id},
            token=token, pending_codes=frozenset({7}), unknown_codes=frozenset({8}),
        )

    def partial_close_position(
        self, token: str, *, account_id: int, contract_id: str, quantity: int
    ) -> MutationResult:
        if quantity != 1:
            raise ValueError("quantity_must_equal_one")
        return self._mutate(
            "/api/Position/partialCloseContract",
            {"accountId": account_id, "contractId": contract_id, "size": 1},
            token=token, pending_codes=frozenset({7}), unknown_codes=frozenset({8}),
        )

    def authenticate(self, credentials: TopstepCredentials) -> SessionToken:
        data = self._post(
            "/api/Auth/loginKey",
            {"userName": credentials.username, "apiKey": credentials.api_key},
        )
        token = _string(data.get("token"), "session_token")
        return SessionToken(token, datetime.now(timezone.utc) + timedelta(hours=23))

    def validate_session(self, token: str) -> SessionToken:
        data = self._post("/api/Auth/validate", {}, token=token)
        new_token = _string(data.get("newToken"), "session_token")
        return SessionToken(new_token, datetime.now(timezone.utc) + timedelta(hours=23))

    def search_active_accounts(self, token: str) -> tuple[LocalAccount, ...]:
        data = self._post("/api/Account/search", {"onlyActiveAccounts": True}, token=token)
        rows = data.get("accounts")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_accounts")
        return tuple(
            LocalAccount(
                id=_int(row.get("id"), "account_id"),
                can_trade=row.get("canTrade") is True,
                is_visible=row.get("isVisible") is True,
            )
            for row in rows
            if isinstance(row, dict)
        )

    def select_exact_account(self, token: str, account_id: int) -> LocalAccount:
        matches = [account for account in self.search_active_accounts(token) if account.id == account_id]
        if len(matches) != 1:
            raise LocalProviderError("exact_account_not_found")
        account = matches[0]
        if not account.can_trade or not account.is_visible:
            raise LocalProviderError("exact_account_not_tradeable")
        return account

    @staticmethod
    def _simulated(live: bool) -> None:
        if live is not False:
            raise LocalProviderError("live_provider_path_prohibited")

    def search_contracts(self, token: str, search_text: str, *, live: bool = False) -> tuple[LocalContract, ...]:
        self._simulated(live)
        data = self._post(
            "/api/Contract/search", {"searchText": search_text, "live": False}, token=token
        )
        rows = data.get("contracts")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_contracts")
        return tuple(self._contract(row) for row in rows if isinstance(row, dict))

    @staticmethod
    def _contract(row: dict[str, Any]) -> LocalContract:
        return LocalContract(
            id=_string(row.get("id"), "contract_id"),
            name=_string(row.get("name"), "contract_name"),
            symbol_id=_string(row.get("symbolId"), "symbol_id", nullable=True),
            tick_size=_decimal_string(row.get("tickSize"), "tick_size"),
            tick_value=_decimal_string(row.get("tickValue"), "tick_value"),
            active=row.get("activeContract") is True,
        )

    def retrieve_bars(
        self, token: str, *, contract_id: str, start: datetime, end: datetime,
        unit: int, unit_number: int, limit: int, live: bool = False,
    ) -> tuple[LocalBar, ...]:
        self._simulated(live)
        if start >= end or not 1 <= limit <= 20_000 or unit not in range(1, 7) or unit_number <= 0:
            raise ValueError("invalid_history_window")
        data = self._post(
            "/api/History/retrieveBars",
            {"contractId": contract_id, "live": False, "startTime": _iso(start),
             "endTime": _iso(end), "unit": unit, "unitNumber": unit_number,
             "limit": limit, "includePartialBar": False},
            token=token, bucket="history",
        )
        rows = data.get("bars")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_bars")
        return tuple(LocalBar(
            timestamp=_string(row.get("t"), "bar_timestamp"),
            open=_decimal_string(row.get("o"), "bar_open"),
            high=_decimal_string(row.get("h"), "bar_high"),
            low=_decimal_string(row.get("l"), "bar_low"),
            close=_decimal_string(row.get("c"), "bar_close"),
            volume=_int(row.get("v"), "bar_volume"),
        ) for row in rows if isinstance(row, dict))

    def search_orders(self, token: str, *, account_id: int, start: datetime,
                      end: datetime | None = None) -> tuple[LocalOrder, ...]:
        return self._orders("/api/Order/search", token,
                            self._window_payload(account_id, start, end))

    def search_open_orders(self, token: str, *, account_id: int) -> tuple[LocalOrder, ...]:
        return self._orders("/api/Order/searchOpen", token, {"accountId": account_id})

    def _orders(self, path: str, token: str, payload: dict[str, Any]) -> tuple[LocalOrder, ...]:
        rows = self._post(path, payload, token=token).get("orders")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_orders")
        return tuple(LocalOrder(
            id=_int(row.get("id"), "order_id"), account_id=_int(row.get("accountId"), "account_id"),
            contract_id=_string(row.get("contractId"), "contract_id"),
            status=_int(row.get("status"), "order_status"),
            order_type=_int(row.get("type"), "order_type"), side=_int(row.get("side"), "order_side"),
            size=_int(row.get("size"), "order_size"),
            limit_price=_decimal_string(row.get("limitPrice"), "limit_price", nullable=True),
            stop_price=_decimal_string(row.get("stopPrice"), "stop_price", nullable=True),
            trail_price=_decimal_string(row.get("trailPrice"), "trail_price", nullable=True),
            custom_tag=_string(row.get("customTag"), "custom_tag", nullable=True),
            creation_timestamp=_string(row.get("creationTimestamp"), "order_timestamp"),
        ) for row in rows if isinstance(row, dict))

    def search_trades(self, token: str, *, account_id: int, start: datetime,
                      end: datetime | None = None) -> tuple[LocalTrade, ...]:
        rows = self._post("/api/Trade/search", self._window_payload(account_id, start, end),
                          token=token).get("trades")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_trades")
        return tuple(LocalTrade(
            id=_int(row.get("id"), "trade_id"), account_id=_int(row.get("accountId"), "account_id"),
            order_id=_int(row.get("orderId"), "order_id"),
            contract_id=_string(row.get("contractId"), "contract_id"),
            side=_int(row.get("side"), "trade_side"), size=_int(row.get("size"), "trade_size"),
            price=_decimal_string(row.get("price"), "trade_price"),
            profit_and_loss=_decimal_string(row.get("profitAndLoss"), "profit_and_loss", nullable=True),
            creation_timestamp=_string(row.get("creationTimestamp"), "trade_timestamp"),
            voided=row.get("voided") is True,
        ) for row in rows if isinstance(row, dict))

    def search_open_positions(self, token: str, *, account_id: int) -> tuple[LocalPosition, ...]:
        rows = self._post("/api/Position/searchOpen", {"accountId": account_id},
                          token=token).get("positions")
        if not isinstance(rows, list):
            raise LocalProviderError("provider_malformed_positions")
        return tuple(LocalPosition(
            id=_int(row.get("id"), "position_id"),
            account_id=_int(row.get("accountId"), "account_id"),
            contract_id=_string(row.get("contractId"), "contract_id"),
            side_type=_int(row.get("type"), "position_type"),
            size=_int(row.get("size"), "position_size"),
            average_price=_decimal_string(row.get("averagePrice"), "average_price"),
            creation_timestamp=_string(row.get("creationTimestamp"), "position_timestamp"),
        ) for row in rows if isinstance(row, dict))

    @staticmethod
    def _window_payload(account_id: int, start: datetime,
                        end: datetime | None) -> dict[str, Any]:
        if end is not None and start >= end:
            raise ValueError("invalid_search_window")
        payload: dict[str, Any] = {"accountId": account_id, "startTimestamp": _iso(start)}
        if end is not None:
            payload["endTimestamp"] = _iso(end)
        return payload
