"""Legacy internal TopstepX helpers.

These helpers are not available to hosted beta users. They deliberately avoid
logging provider bodies, credentials, authorization headers, order payloads,
or tokens.
"""

import requests

BASE_URL = "https://api.topstepx.com"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_active_account_id(token: str):
    """Account selection is never inferred; the durable approval service owns it."""
    return None


def get_contract_id(symbol: str, token: str):
    try:
        response = requests.post(
            f"{BASE_URL}/api/Contract/search",
            headers=_headers(token),
            json={"searchText": symbol.upper(), "live": False},
            timeout=20,
        )
        response.raise_for_status()
        contracts = response.json().get("contracts") or []
        for contract in contracts:
            if symbol.upper() in (contract.get("name"), contract.get("description")):
                return contract.get("id")
    except (requests.RequestException, ValueError):
        return None
    return None


def get_all_contracts(token: str):
    try:
        response = requests.post(
            f"{BASE_URL}/api/Contract/search",
            headers=_headers(token),
            json={"searchText": "", "live": False},
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("contracts") or []
    except (requests.RequestException, ValueError):
        return []


def execute_trade(symbol: str, side: str, quantity: int, token: str):
    """Fail closed until the durable provider-execution slice is implemented."""
    return {"success": False, "errorMessage": "Provider order submission is disabled."}
