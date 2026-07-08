import json

import pytest

import trade
from cdc_lib.api import ApiResponse
from cdc_lib.output import SkillExit


def _capture(func, *args):
    with pytest.raises(SkillExit) as exc_info:
        func(*args)
    return exc_info.value


def test_quote_purchase_success(monkeypatch, capsys):
    captured = {}

    def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return ApiResponse(200, {"ok": True, "quotation": {"id": "q1", "rate": "50000"}})

    monkeypatch.setattr(trade, "api_post", fake_post)

    params = json.dumps({"from_currency": "USD", "to_currency": "BTC", "from_amount": "100"})
    exc = _capture(trade.quote, "purchase", params)

    assert exc.code == 0
    assert captured["path"] == "/v1/crypto-purchase/quotations"
    assert captured["body"] == {"from_currency": "USD", "to_currency": "BTC", "from_amount": "100"}
    assert '"id": "q1"' in capsys.readouterr().out


def test_quote_invalid_type_fails():
    exc = _capture(trade.quote, "bogus", "{}")
    assert exc.code == 1


def test_quote_missing_json_fails():
    exc = _capture(trade.quote, "purchase", "")
    assert exc.code == 1


def test_quote_rejected_by_api(monkeypatch):
    monkeypatch.setattr(
        trade, "api_post",
        lambda path, body: ApiResponse(400, {"ok": False, "error": "insufficient_funds", "error_message": "no cash"}),
    )
    exc = _capture(trade.quote, "purchase", json.dumps({"from_currency": "USD", "to_currency": "BTC", "from_amount": "1"}))
    assert exc.code == 1


def test_confirm_purchase_success(monkeypatch, capsys):
    captured = {}

    def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return ApiResponse(200, {"ok": True, "transaction": {"status": "completed"}})

    monkeypatch.setattr(trade, "api_post", fake_post)
    exc = _capture(trade.confirm, "purchase", "quote-123")

    assert exc.code == 0
    assert captured["body"] == {"quotation_id": "quote-123"}
    assert "completed" in capsys.readouterr().out


def test_confirm_exchange_includes_side(monkeypatch):
    captured = {}

    def fake_post(path, body):
        captured["body"] = body
        return ApiResponse(200, {"ok": True, "transaction": {}})

    monkeypatch.setattr(trade, "api_post", fake_post)
    _capture(trade.confirm, "exchange", "quote-9")
    assert captured["body"] == {"quotation_id": "quote-9", "side": "buy"}


def test_confirm_missing_quotation_id_fails():
    exc = _capture(trade.confirm, "purchase", None)
    assert exc.code == 1


def test_history_returns_last_five(monkeypatch, capsys):
    txns = [{"id": i} for i in range(10)]
    monkeypatch.setattr(trade, "api_get", lambda path: ApiResponse(200, {"ok": True, "transactions": txns}))
    exc = _capture(trade.history)
    assert exc.code == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["data"]) == 5
