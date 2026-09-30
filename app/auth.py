"""Legacy TopstepX authentication helper.

Hosted beta code must not call this helper. It remains only for compatibility
with internal paper-mode utilities and deliberately never logs provider
requests, responses, credentials, or tokens.
"""

import os

import requests
from dotenv import load_dotenv
from requests.exceptions import RequestException

load_dotenv()

LOGIN_URL = "https://api.topstepx.com/api/Auth/loginKey"


def get_session_token() -> str:
    payload = {
        "userName": os.getenv("TOPSTEP_USER"),
        "apiKey": os.getenv("TOPSTEP_API_KEY"),
    }
    headers = {"accept": "text/plain", "Content-Type": "application/json"}
    try:
        response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (RequestException, ValueError) as exc:
        raise RuntimeError("Authentication provider request failed.") from exc
    token = data.get("token") if data.get("success") else None
    if not token:
        raise RuntimeError("Authentication provider rejected the request.")
    return token
