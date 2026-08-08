"""
Tests for cdcx/predictions.py -- the thin client for the public Crypto.com
Predictions Market Data API. All HTTP calls are mocked (no live network --
this sandbox can't reach crypto.com anyway); these lock in the request
shape (URL, params, headers) and the response parsing against the REAL
schema, captured from a live `curl` on a machine that can reach
data-api.crypto.com (see predictions.py's module docstring).
"""

from types import SimpleNamespace

import pytest

from cdcx.predictions import (
    Contract,
    ContractPrice,
    PredictionEvent,
    PredictionsClient,
    PredictionsNotFound,
    PredictionsRateLimited,
    format_contract_price,
    format_events,
)


def _fake_response(json_data, status_code=200, headers=None):
    def raise_for_status():
        if status_code >= 400 and status_code != 429 and status_code != 404:
            raise RuntimeError(f"HTTP {status_code}")

    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: json_data,
        raise_for_status=raise_for_status,
    )


# A real event row, trimmed to the fields that matter, from a live capture.
_REAL_EVENT_ROW = {
    "id": "80a1fa14-f1cf-4a65-8897-0b89ee28d56d",
    "title": "Green Bay @ Pittsburgh",
    "kind": "NFL",
    "type": "match",
    "status": "active",
    "contracts_count": 2,
    "contracts": [
        {
            "id": "86a79d74-485b-5116-b628-a39b4b98f53d",
            "symbol": "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO",
            "title": "Green Bay",
            "status": "active",
            "yes": "0.42",
            "no": "0.58",
            "chance": "42.00",
            "payout_per_100": "232.56",
        },
        {
            "id": "80f1ef71-b6ab-5ba9-a3af-62af538d7e86",
            "symbol": "NFL-00002-260813-M-Steelers-012_270301-2300_1_PM.NPO",
            "title": "Pittsburgh",
            "status": "active",
            "yes": "0.58",
            "no": "0.45",
            "chance": "58.00",
            "payout_per_100": "172.41",
        },
    ],
}


# ---------------------------------------------------------------------------
# PredictionsClient.list_events -- real schema (nested contracts[])
# ---------------------------------------------------------------------------

def test_list_events_parses_title_kind_and_nested_contracts(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _fake_response({"data": [_REAL_EVENT_ROW]})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    client = PredictionsClient()
    events = client.list_events(kind="NFL", limit=5)

    assert captured["url"].endswith("/events")
    assert captured["params"] == {"limit": 5, "kind": "NFL"}
    assert len(events) == 1

    ev = events[0]
    assert ev.title == "Green Bay @ Pittsburgh"
    assert ev.kind == "NFL"
    assert len(ev.contracts) == 2

    packers = ev.contracts[0]
    assert isinstance(packers, Contract)
    assert packers.symbol == "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO"
    assert packers.title == "Green Bay"
    assert packers.yes_price == pytest.approx(0.42)
    assert packers.no_price == pytest.approx(0.58)
    assert packers.chance_pct == pytest.approx(42.00)
    assert packers.payout_per_100 == pytest.approx(232.56)


def test_list_events_without_kind_omits_it_from_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _fake_response({"data": []})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    PredictionsClient().list_events(limit=10)
    assert captured["params"] == {"limit": 10}


def test_event_with_no_contracts_field_parses_to_empty_list(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({"data": [{"id": "1", "title": "X", "kind": "CRYPT"}]})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    events = PredictionsClient().list_events()
    assert events[0].contracts == []


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
        return _fake_response({"data": [{"id": "2", "title": "Election 2028", "kind": "ELECT"}]})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    events = PredictionsClient().search_events("election", limit=3)
    assert captured["url"].endswith("/events/search")
    assert captured["params"] == {"q": "election", "limit": 3}
    assert events[0].title == "Election 2028"


# ---------------------------------------------------------------------------
# PredictionsClient.get_contract_price -- real field names, confirmed via a
# pretty-printed (curl | python3 -m json.tool) live response: bid/ask/mid/
# probability/spread. A genuinely different shape from the yes/no/chance
# fields nested in /events -- see module docstring.
# ---------------------------------------------------------------------------

_REAL_CONTRACT_PRICE_ROW = {
    "symbol": "BTCUSD_260808-2100_6538400_B.NXO",
    "title": "Above $65,384.00",
    "status": "active",
    "bid": "0",
    "ask": "0.10",
    "mid": "0.05",
    "probability": "10.00",
    "spread": "0.10",
    "updated_at": "2026-08-08T20:50:51.066+00:00",
}


def test_get_contract_price_reads_real_bid_ask_mid_probability_fields(monkeypatch):
    ticker = "BTCUSD_260808-2100_6538400_B.NXO"

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url.endswith(f"/contracts/{ticker}/price")
        return _fake_response({"data": _REAL_CONTRACT_PRICE_ROW})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    price = PredictionsClient().get_contract_price(ticker)
    assert price.title == "Above $65,384.00"
    assert price.status == "active"
    assert price.bid == pytest.approx(0.0)
    assert price.ask == pytest.approx(0.10)
    assert price.mid == pytest.approx(0.05)
    assert price.probability_pct == pytest.approx(10.00)
    assert price.spread == pytest.approx(0.10)


def test_get_contract_price_keeps_raw_when_no_known_fields_present(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({"data": {"something_else": 1}})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    price = PredictionsClient().get_contract_price("X")
    assert price.bid is None
    assert price.ask is None
    assert price.probability_pct is None
    assert price.raw == {"data": {"something_else": 1}}


# ---------------------------------------------------------------------------
# Rate limiting / not found
# ---------------------------------------------------------------------------

def test_429_raises_predictions_rate_limited_with_retry_after(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({}, status_code=429, headers={"Retry-After": "42"})

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    with pytest.raises(PredictionsRateLimited, match="42"):
        PredictionsClient().list_events()


def test_404_raises_predictions_not_found_with_a_clear_message(monkeypatch):
    # Regression test: confirmed live -- "BTC-YES" and "BTC" (the docs'
    # illustrative example / a guessed short ticker) both 404 in practice,
    # since real tickers are the long `symbol` values nested in /events.
    def fake_get(url, params=None, headers=None, timeout=None):
        return _fake_response({}, status_code=404)

    monkeypatch.setattr("cdcx.predictions.requests.get", fake_get)

    with pytest.raises(PredictionsNotFound, match="not a real one"):
        PredictionsClient().get_contract_price("BTC-YES")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_format_events_lists_title_kind_and_each_contract_symbol():
    ev = PredictionEvent(
        id="1", title="Green Bay @ Pittsburgh", kind="NFL",
        contracts=[
            Contract(
                id="c1", symbol="NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO",
                title="Green Bay", status="active",
                yes_price=0.42, no_price=0.58, chance_pct=42.0, payout_per_100=232.56,
            ),
        ],
    )
    out = format_events("PREDICTION MARKET EVENTS", [ev])
    assert "Green Bay @ Pittsburgh" in out
    assert "NFL" in out
    assert "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO" in out
    assert "0.42" in out


def test_format_events_handles_empty_list():
    out = format_events("PREDICTION MARKET EVENTS", [])
    assert "no events returned" in out


def test_format_contract_price_shows_probability_and_order_book_fields():
    price = ContractPrice(
        ticker="BTCUSD_260808-2100_6538400_B.NXO", title="Above $65,384.00", status="active",
        bid=0.0, ask=0.10, mid=0.05, probability_pct=10.00, spread=0.10,
    )
    out = format_contract_price(price)
    assert "10.00%" in out
    assert "Probability" in out
    assert "Bid" in out and "Ask" in out


def test_format_contract_price_falls_back_to_raw_when_unparsed():
    price = ContractPrice(ticker="X", raw={"foo": "bar"})
    out = format_contract_price(price)
    assert "raw" in out.lower()
    assert "foo" in out
