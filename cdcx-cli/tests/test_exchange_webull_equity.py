import pytest

from cdcx.exchange.webull_equity import (
    _extract_bar_list, _parse_history_bar_response, _normalize_timestamp,
    WebullEquityExchange, DEFAULT_SANDBOX_HOST,
)


class _FakeResponse:
    """Stands in for the raw `requests.Response` the SDK returns -- see
    webull_equity.py's module docstring on why the SDK leaves JSON parsing
    to the caller."""
    def __init__(self, body, status_ok=True):
        self._body = body
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("simulated HTTP error")

    def json(self):
        return self._body


def test_extract_bar_list_accepts_a_bare_list():
    assert _extract_bar_list(_FakeResponse([{"a": 1}])) == [{"a": 1}]


@pytest.mark.parametrize("key", ["data", "bars", "items", "result", "results"])
def test_extract_bar_list_accepts_common_wrapper_keys(key):
    assert _extract_bar_list(_FakeResponse({key: [{"a": 1}]})) == [{"a": 1}]


def test_extract_bar_list_raises_clearly_on_unexpected_shape():
    with pytest.raises(RuntimeError, match="Unexpected Webull response shape"):
        _extract_bar_list(_FakeResponse({"nonsense": "value"}))


def test_parse_history_bar_response_accepts_short_field_names():
    rows = [
        {"t": 1799500200, "o": 150.0, "h": 151.0, "l": 149.5, "c": 150.8, "v": 1_000_000},
        {"t": 1799503800, "o": 150.8, "h": 152.0, "l": 150.5, "c": 151.9, "v": 900_000},
    ]
    data = _parse_history_bar_response(rows)
    assert data.opens == [150.0, 150.8]
    assert data.closes == [150.8, 151.9]


def test_parse_history_bar_response_accepts_camelcase_field_names():
    rows = [{"timestamp": 1799500200, "openPrice": 1, "highPrice": 2, "lowPrice": 0.5, "closePrice": 1.5, "volume": 10}]
    data = _parse_history_bar_response(rows)
    assert data.opens == [1.0]
    assert data.closes == [1.5]


def test_parse_history_bar_response_normalizes_descending_order_to_ascending():
    rows = [
        {"t": 200, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},  # most-recent-first
        {"t": 100, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ]
    data = _parse_history_bar_response(rows)
    assert data.timestamps == [100, 200]
    assert data.closes == [1.0, 2.0]  # chronological order preserved after the flip


def test_parse_history_bar_response_raises_a_clear_error_naming_the_missing_field():
    rows = [{"o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]  # no timestamp field at all
    with pytest.raises(RuntimeError, match="Could not find a 'timestamp' field"):
        _parse_history_bar_response(rows)


def test_parse_history_bar_response_raises_on_empty_bars():
    with pytest.raises(RuntimeError, match="no historical bars"):
        _parse_history_bar_response([])


def test_normalize_timestamp_seconds_vs_milliseconds_heuristic():
    assert _normalize_timestamp(1799500200) == 1799500200          # already seconds
    assert _normalize_timestamp(1799500200000) == 1799500200       # milliseconds
    assert _normalize_timestamp("1799500200") == 1799500200        # numeric string


def test_normalize_timestamp_accepts_iso8601():
    assert _normalize_timestamp("2026-01-09T13:30:00Z") == 1767965400


# --- environment selection (production vs sandbox) -------------------------
# Real bug this covers: a Paper Trading app on developer.webull.com is
# rejected with HTTP 401 "ensure you are connecting to the correct
# environment" against the production host -- see module docstring and
# https://developer.webull.com/apis/docs/sdk. These tests spy on
# ApiClient.add_endpoint rather than hitting the network.

def _spy_add_endpoint(monkeypatch):
    calls = []
    from webull.core.client import ApiClient
    from webull.core.http.initializer.client_initializer import ClientInitializer
    monkeypatch.setattr(ApiClient, "add_endpoint", lambda self, region_id, endpoint, api_type=None: calls.append((region_id, endpoint)))
    # DataClient(api_client) construction runs ClientInitializer.initializer(),
    # which makes a REAL /openapi/config network handshake -- stub it out so
    # these tests exercise only the endpoint-selection logic, not the network.
    monkeypatch.setattr(ClientInitializer, "initializer", staticmethod(lambda api_client: None))
    return calls


def test_production_is_the_default_and_does_not_touch_the_endpoint(monkeypatch):
    monkeypatch.delenv("WEBULL_ENVIRONMENT", raising=False)  # isolate from the real .env's WEBULL_ENVIRONMENT
    calls = _spy_add_endpoint(monkeypatch)
    WebullEquityExchange(app_key="k", app_secret="s", region_id="us")
    assert calls == []


@pytest.mark.parametrize("env", ["sandbox", "paper", "paper_trading", "paper-trading", "SANDBOX"])
def test_sandbox_style_environment_values_switch_to_the_sandbox_host(monkeypatch, env):
    calls = _spy_add_endpoint(monkeypatch)
    WebullEquityExchange(app_key="k", app_secret="s", region_id="us", environment=env)
    assert calls == [("us", DEFAULT_SANDBOX_HOST)]


def test_webull_sandbox_host_env_var_overrides_the_default(monkeypatch):
    monkeypatch.setenv("WEBULL_SANDBOX_HOST", "custom.sandbox.example.com")
    calls = _spy_add_endpoint(monkeypatch)
    WebullEquityExchange(app_key="k", app_secret="s", region_id="us", environment="sandbox")
    assert calls == [("us", "custom.sandbox.example.com")]


def test_webull_environment_env_var_is_read_when_not_passed_explicitly(monkeypatch):
    monkeypatch.setenv("WEBULL_ENVIRONMENT", "sandbox")
    calls = _spy_add_endpoint(monkeypatch)
    WebullEquityExchange(app_key="k", app_secret="s", region_id="us")
    assert calls == [("us", DEFAULT_SANDBOX_HOST)]


# --- weekly bar stamping -----------------------------------------------------
# Real shape from the Webull market-data API (2026-09-27): weekly bars are
# stamped with the week's LAST session. SPY's Sep 21-25 week:
_WEBULL_SPY_WEEKS = [
    {"time": "2026-09-18T04:00:00.000+0000", "open": "757.120083", "close": "761.69",
     "high": "762.00", "low": "747.743365", "volume": "268966609"},
    {"time": "2026-09-25T04:00:00.000+0000", "open": "766.251", "close": "771.35",
     "high": "775.14", "low": "763.245", "volume": "220869101"},
]


def _utc_midnight(y, m, d):
    from datetime import datetime, timezone
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def _fake_webull_exchange(rows, seen_timespans):
    from types import SimpleNamespace

    exchange = object.__new__(WebullEquityExchange)
    exchange._Timespan = SimpleNamespace(M60="M60", M240="M240", D="D", W="W")
    exchange._Category = SimpleNamespace(US_STOCK="US_STOCK")

    def get_history_bar(symbol, category, timespan, count):
        seen_timespans.append(timespan)
        return _FakeResponse(rows)

    exchange._data_client = SimpleNamespace(market_data=SimpleNamespace(get_history_bar=get_history_bar))
    return exchange


def test_weekly_bars_are_restamped_to_monday_of_their_week():
    seen = []
    data = _fake_webull_exchange(_WEBULL_SPY_WEEKS, seen).fetch_ohlcv("SPY", timeframe="1w")
    assert seen == ["W"]
    assert data.timestamps == [_utc_midnight(2026, 9, 14), _utc_midnight(2026, 9, 21)]
    assert data.closes == [761.69, 771.35]          # values untouched
    assert data.volumes == [268966609.0, 220869101.0]


def test_finished_webull_week_is_not_treated_as_forming_the_following_week():
    from datetime import datetime, timezone
    from cdcx.no_trade_gate import last_bar_is_forming

    data = _fake_webull_exchange(_WEBULL_SPY_WEEKS, []).fetch_ohlcv("SPY", timeframe="1w")
    next_wednesday = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc).timestamp()
    assert last_bar_is_forming(data.timestamps, "1w", next_wednesday) is False


def test_daily_webull_bars_keep_their_own_stamp():
    rows = [
        {"time": "2026-09-24T04:00:00.000+0000", "open": "1", "close": "1", "high": "1", "low": "1", "volume": "1"},
        {"time": "2026-09-25T04:00:00.000+0000", "open": "1", "close": "1", "high": "1", "low": "1", "volume": "1"},
    ]
    data = _fake_webull_exchange(rows, []).fetch_ohlcv("SPY", timeframe="1d")
    assert data.timestamps == [_utc_midnight(2026, 9, 24) + 4 * 3600, _utc_midnight(2026, 9, 25) + 4 * 3600]


def test_webull_bars_are_tagged_us_equity():
    data = _fake_webull_exchange(_WEBULL_SPY_WEEKS, []).fetch_ohlcv("SPY", timeframe="1w")
    assert data.market == "us_equity"
