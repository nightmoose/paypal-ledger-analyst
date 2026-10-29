"""Minimal PayPal REST client (sandbox only)."""
import os, time, uuid
import httpx

BASE = "https://api-m.sandbox.paypal.com"  # sandbox is hard-coded on purpose
_tok = {"v": None, "exp": 0}


def token() -> str:
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    r = httpx.post(f"{BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                   auth=(os.environ["PAYPAL_SANDBOX_CLIENT_ID"], os.environ["PAYPAL_SANDBOX_SECRET"]), timeout=30)
    r.raise_for_status()
    j = r.json()
    _tok.update(v=j["access_token"], exp=time.time() + j.get("expires_in", 3000))
    return _tok["v"]


def call(method: str, path: str, json=None, params=None, idem: bool = True) -> httpx.Response:
    h = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Prefer": "return=representation"}
    if idem and method in ("POST", "PATCH"):
        h["PayPal-Request-Id"] = str(uuid.uuid4())
    return httpx.request(method, BASE + path, headers=h, json=json, params=params, timeout=60)
