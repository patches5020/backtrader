import base64
import hashlib
import hmac
import os

import pytest

from cdc_lib import api
from cdc_lib.output import SkillExit


def test_get_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("CDC_API_KEY", "k")
    monkeypatch.setenv("CDC_API_SECRET", "s")
    assert api.get_credentials() == ("k", "s")


def test_get_credentials_fails_when_missing(monkeypatch):
    monkeypatch.delenv("CDC_API_KEY", raising=False)
    monkeypatch.delenv("CDC_API_SECRET", raising=False)
    with pytest.raises(SkillExit) as exc_info:
        api.get_credentials()
    assert exc_info.value.code == 1


def test_signed_headers_matches_manual_hmac(monkeypatch):
    monkeypatch.setenv("CDC_API_KEY", "my-key")
    monkeypatch.setenv("CDC_API_SECRET", "my-secret")

    headers = api._signed_headers("GET", "/v1/fiat-account")
    timestamp = headers["Cdc-Api-Timestamp"]

    expected_payload = f"{timestamp}GET/v1/fiat-account"
    expected_sig = base64.b64encode(
        hmac.new(b"my-secret", expected_payload.encode(), hashlib.sha256).digest()
    ).decode()

    assert headers["Cdc-Api-Key"] == "my-key"
    assert headers["Cdc-Api-Signature"] == expected_sig
    assert "Content-Type" not in headers


def test_signed_headers_includes_body_in_signature(monkeypatch):
    monkeypatch.setenv("CDC_API_KEY", "k")
    monkeypatch.setenv("CDC_API_SECRET", "s")

    body = {"a": 1}
    headers = api._signed_headers("POST", "/v1/foo", body)
    assert headers["Content-Type"] == "application/json"


def test_assert_ok_passes_for_200_ok_true():
    res = api.ApiResponse(status=200, data={"ok": True})
    api.assert_ok(res, "ctx")  # should not raise


def test_assert_ok_fails_for_non_ok():
    res = api.ApiResponse(status=200, data={"ok": False, "error": "bad_request", "error_message": "nope"})
    with pytest.raises(SkillExit) as exc_info:
        api.assert_ok(res, "ctx")
    assert exc_info.value.code == 1


def test_assert_ok_fails_for_rate_limit():
    res = api.ApiResponse(status=429, data={})
    with pytest.raises(SkillExit):
        api.assert_ok(res, "ctx")
