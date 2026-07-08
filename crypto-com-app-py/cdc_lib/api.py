"""Crypto.com App API client: HMAC-signed requests, ported from scripts/lib/api.ts.

Credentials are read from CDC_API_KEY / CDC_API_SECRET environment variables
only. They are never written to a file or hardcoded here.
"""
import base64
import hashlib
import hmac
import json
import os
import platform
import time
from dataclasses import dataclass

import requests

from cdc_lib.output import ErrorCode, fail

BASE_URL = "https://wapi.crypto.com"


def get_credentials():
    api_key = os.environ.get("CDC_API_KEY")
    api_secret = os.environ.get("CDC_API_SECRET")
    if not api_key or not api_secret:
        fail(
            ErrorCode.MISSING_ENV,
            'CDC_API_KEY and/or CDC_API_SECRET not set. Run:\n'
            '  export CDC_API_KEY="your-key"\n'
            '  export CDC_API_SECRET="your-secret"',
        )
    return api_key, api_secret


def _signed_headers(method, path, body=None):
    api_key, api_secret = get_credentials()
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    sign_payload = f"{timestamp}{method.upper()}{path}{body_str}"
    signature = base64.b64encode(
        hmac.new(api_secret.encode("utf-8"), sign_payload.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    user_agent = f"Python/{platform.python_version()} {platform.system()}/{platform.release()}-cdc-clawbot/1.0"

    headers = {
        "User-Agent": user_agent,
        "Cdc-Api-Key": api_key,
        "Cdc-Api-Timestamp": timestamp,
        "Cdc-Api-Signature": signature,
    }
    if body:
        headers["Content-Type"] = "application/json"
    return headers


@dataclass
class ApiResponse:
    status: int
    data: dict


def _request(method, path, body=None):
    sign_path = path.split("?")[0]
    headers = _signed_headers(method, sign_path, body)
    url = f"{BASE_URL}{path}"

    response = requests.request(
        method, url, headers=headers, data=json.dumps(body) if body else None, timeout=15,
    )

    try:
        data = response.json()
    except ValueError:
        fail(ErrorCode.API_ERROR, f"Non-JSON response from {method} {path} (HTTP {response.status_code})")

    return ApiResponse(status=response.status_code, data=data)


def api_get(path):
    return _request("GET", path)


def api_post(path, body=None):
    return _request("POST", path, body)


def assert_ok(res, context):
    if res.status == 429:
        fail(ErrorCode.RATE_LIMITED, f"{context}: Rate limit exceeded. Wait 60 seconds before retrying.")
    if res.status != 200 or (res.data or {}).get("ok") is not True:
        api_error = (res.data or {}).get("error") or (res.data or {}).get("code")
        api_msg = (res.data or {}).get("error_message") or (res.data or {}).get("message")
        if api_msg and api_error:
            detail = f"{api_error}: {api_msg}"
        else:
            detail = api_error or api_msg or f"HTTP {res.status}"
        fail(ErrorCode.API_ERROR, f"{context}: {detail}")
