import pytest

import account
from cdc_lib.api import ApiResponse
from cdc_lib.output import SkillExit


def _capture(func, *args):
    with pytest.raises(SkillExit) as exc_info:
        func(*args)
    return exc_info.value


def test_balances_all_filters_zero_amounts(monkeypatch, capsys):
    def fake_get(path):
        if path == "/v1/fiat-account":
            return ApiResponse(200, {"ok": True, "account": {"balances": [
                {"currency": "USD", "amount": {"amount": "0"}},
                {"currency": "EUR", "amount": {"amount": "50"}},
            ]}})
        if path == "/v1/crypto-account":
            return ApiResponse(200, {"ok": True, "account": {"wallets": [
                {"currency": "BTC", "available": {"amount": "0.5"}},
                {"currency": "ETH", "available": {"amount": "0"}, "balance": {"amount": "0"}},
            ]}})
        if path == "/v1/portfolio":
            return ApiResponse(200, {"ok": True, "products": []})
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(account, "api_get", fake_get)

    exc = _capture(account.balances, "all")
    assert exc.code == 0

    out = capsys.readouterr().out
    assert "EUR" in out and "USD" not in out
    assert '"currency": "BTC"' in out
    assert "ETH" not in out


def test_balances_invalid_scope_fails():
    exc = _capture(account.balances, "bogus")
    assert exc.code == 1


def test_balance_single_symbol(monkeypatch, capsys):
    def fake_get(path):
        if path == "/v1/crypto-account":
            return ApiResponse(200, {"ok": True, "account": {"wallets": [
                {"currency": "BTC", "available": {"amount": "1.5"}, "balance": {"amount": "1.5"}},
            ]}})
        if "currency_allocation" in path:
            return ApiResponse(200, {"ok": True})
        raise AssertionError(path)

    monkeypatch.setattr(account, "api_get", fake_get)
    exc = _capture(account.balance, "btc")
    assert exc.code == 0
    assert '"available": "1.5"' in capsys.readouterr().out


def test_trading_limit_computes_used(monkeypatch, capsys):
    def fake_get(path):
        return ApiResponse(200, {"ok": True, "api_key": {
            "weekly_trading_limit_in_usd": "1000",
            "remaining_weekly_trading_limit_in_usd": "600",
        }})

    monkeypatch.setattr(account, "api_get", fake_get)
    exc = _capture(account.trading_limit)
    assert exc.code == 0
    out = capsys.readouterr().out
    assert '"used": 400.0' in out


def test_resolve_source_ambiguous(monkeypatch, capsys):
    def fake_get(path):
        return ApiResponse(200, {"ok": True, "account": {"wallets": [
            {"currency": "BTC", "available": {"amount": "1"}},
            {"currency": "ETH", "available": {"amount": "2"}},
        ]}})

    monkeypatch.setattr(account, "api_get", fake_get)
    exc = _capture(account.resolve_source, "sale")
    assert exc.code == 0
    assert '"status": "AMBIGUOUS"' in capsys.readouterr().out


def test_revoke_key_success(monkeypatch, capsys):
    monkeypatch.setattr(account, "api_post", lambda path, body: ApiResponse(200, {"ok": True}))
    exc = _capture(account.revoke_key)
    assert exc.code == 0
    assert '"revoked": true' in capsys.readouterr().out
