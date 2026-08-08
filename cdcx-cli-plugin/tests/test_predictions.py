"""
Tests for cdcx/predictions.py -- the thin client for the public Crypto.com
Predictions Market Data API. All HTTP calls are mocked (no live network --
this sandbox can't reach crypto.com anyway); these lock in the request
shape (URL, params, headers) and the response parsing, not live data.
"""

from types import SimpleNamespace

import pytest

from cdcx.predictions import (
    ContractPrice,
    PredictionEvent,
    PredictionsClient,
    PredictionsRateLimited,
    format_contract_price,
    format_events,
)


def _fake_response(json_data, status_code=200, headers=None):
    def raise_for_status():
        if status_code >= 400 and status_code != 429:
            raise RuntimeError(f"HTTP {status_code}")

    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: json_data,
        raise_for_status=raise_for_status,
    )


# ---------------------------------------------------------------------------
# PredictionsClient.list_events
# ---------------------------------------------------------------------------

def test_list_events_parses_title_and_kind(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _fake_response({"data": [{"id": "1", "title": "Super Bowl LX", "kind": "NFL"}]})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    client = PredictionsClient()
    events = client.list_events(kind="NFL", limit=5)

    assert captured["url"].endswith("/events")
    assert captured["params"] == {"limit": 5, "kind": "NFL"}
    assert captured["headers"] == {}
    assert len(events) == 1
    assert events[0] == PredictionEvent(id="1", title="Super Bowl LX", kind="NFL", raw=events[0].raw)


def test_list_events_without_kind_omits_it_from_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _fake_response({"data": []})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    PredictionsClient().list_events(limit=10)
    assert captured["params"] == {"limit": 10}


def test_api_key_sent_as_header_when_configured(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        return _fake_response({"data": []})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    PredictionsClient(api_key="mdla_test_key").list_events()
    assert captured["headers"] == {"X-API-Key": "mdla_test_key"}


# ---------------------------------------------------------------------------
# PredictionsClient.search_events
# ---------------------------------------------------------------------------

def test_search_events_passes_query_param(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _fake_response({"data": [{"id": "2", "title": "Election 2028", "kind": "POLITICS"}]})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    events = PredictionsClient().search_events("election", limit=3)
    assert captured["url"].endswith("/events/search")
    assert captured["params"] == {"q": "election", "limit": 3}
    assert events[0].title == "Election 2028"


# ---------------------------------------------------------------------------
# PredictionsClient.get_contract_price
# ---------------------------------------------------------------------------

def test_get_contract_price_reads_yes_no_fields(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert url.endswith("/contracts/BTC-YES/price")
        return _fake_response({"data": {"yes_price": 0.63, "no_price": 0.37}})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    price = PredictionsClient().get_contract_price("BTC-YES")
    assert price == ContractPrice(ticker="BTC-YES", yes_price=0.63, no_price=0.37, raw=price.raw)


def test_get_contract_price_falls_back_to_last_price(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({"data": {"last_price": 0.2}})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    price = PredictionsClient().get_contract_price("SOME-TICKER")
    assert price.yes_price == 0.2
    assert price.no_price == pytest.approx(0.8)


def test_get_contract_price_keeps_raw_when_no_known_fields_present(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({"data": {"something_else": 1}})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    price = PredictionsClient().get_contract_price("X")
    assert price.yes_price is None
    assert price.no_price is None
    assert price.raw == {"data": {"something_else": 1}}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_429_raises_predictions_rate_limited_with_retry_after(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({}, status_code=429, headers={"Retry-After": "42"})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    with pytest.raises(PredictionsRateLimited, match="42"):
        PredictionsClient().list_events()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_format_events_lists_each_title_and_kind():
    events = [PredictionEvent(id="1", title="Super Bowl LX", kind="NFL")]
    out = format_events("PREDICTION MARKET EVENTS", events)
    assert "Super Bowl LX" in out
    assert "NFL" in out


def test_format_events_handles_empty_list():
    out = format_events("PREDICTION MARKET EVENTS", [])
    assert "no events returned" in out


def test_format_contract_price_shows_implied_probability():
    price = ContractPrice(ticker="BTC-YES", yes_price=0.63, no_price=0.37)
    out = format_contract_price(price)
    assert "BTC-YES" in out
    assert "63.0%" in out


def test_format_contract_price_falls_back_to_raw_when_unparsed():
    price = ContractPrice(ticker="X", yes_price=None, no_price=None, raw={"foo": "bar"})
    out = format_contract_price(price)
    assert "raw" in out.lower()
    assert "foo" in out
