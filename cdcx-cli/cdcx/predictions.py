"""
predictions.py
---------------
Thin client for the public Crypto.com Predictions Market Data API
(https://data.crypto.com -- a separate product from both the App API and
the Exchange API this project otherwise talks to). Prediction markets are
binary-outcome contracts (sports, crypto price thresholds, and similar
events) priced by a live order book: a YES share trading at 0.63 means the
market is pricing that outcome at roughly a 63% chance.

Read-only market data is open to anonymous access -- no API key required.
Crypto.com rate-limits anonymous access at 100 requests/minute and 50,000
requests/day per IP; exceeding either gets a 429 with a `Retry-After`
header, surfaced here as `PredictionsRateLimited` rather than a generic
HTTP error. A licensed Market Data License (MDLA) key raises those limits
and is sent via the `X-API-Key` header when `PREDICTIONS_API_KEY` is set
in .env -- every method here works fine without one.

Endpoints wrapped (see the quickstart at https://data.crypto.com/quickstart):
    GET /events                 -- list events, optionally filtered by `kind`
    GET /events/search          -- full-text search across events
    GET /contracts/{ticker}/price -- real-time pricing for one contract

Schema confirmed against a real response (captured from a live `curl` on a
machine that can reach data-api.crypto.com -- this project's own sandbox
cannot). Each event looks like:

    {"id": "...", "title": "Green Bay @ Pittsburgh", "kind": "NFL",
     "type": "match", "event_date": "...", "status": "active",
     "contracts_count": 2, "market_format": "head_to_head",
     "metadata": {...},
     "contracts": [
        {"id": "...", "symbol": "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO",
         "title": "Green Bay", "status": "active",
         "yes": "0.58", "no": "0.45", "chance": "58.00",
         "payout_per_100": "172.41", "team": {...}, "market_type": {...}},
        ...
     ]}

The important, non-obvious thing this confirmed: **a contract's real
identifier is its `symbol`** (a long structured string like the one
above) -- NOT a short asset-style code like "BTC-YES". That exact ticker
is the quickstart docs' own illustrative example and 404s in practice
(confirmed live) -- real tickers only come from the `contracts[].symbol`
field of an `/events` (or `/events/search`) response. `get_contract_price`
still takes whatever ticker string you give it; get a real one from
`--predictions`/`--predictions-search` first.

`GET /contracts/{ticker}/price` itself uses a genuinely different shape
from the nested event contracts above -- also confirmed against a real,
pretty-printed response (`curl ... | python3 -m json.tool`, to rule out
terminal line-wrapping hiding a field):

    {"data": {"symbol": "BTCUSD_260808-2100_6538400_B.NXO",
               "title": "Above $65,384.00", "status": "active",
               "bid": "0", "ask": "0.10", "mid": "0.05",
               "probability": "10.00", "spread": "0.10",
               "updated_at": "..."}}

Order-book style (`bid`/`ask`/`mid`/`spread`) plus a `probability`
percentage -- not `yes`/`no`/`chance` like the nested event contracts.
Both shapes are real and confirmed; they just don't match each other,
which is a real quirk of this API, not an inconsistency in this client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import requests

PREDICTIONS_API_BASE = "https://data-api.crypto.com/api/v1/predictions"
DEFAULT_TIMEOUT = 10


class PredictionsRateLimited(RuntimeError):
    """Raised on a 429 from the Predictions API -- back off, don't retry immediately."""


class PredictionsNotFound(RuntimeError):
    """Raised on a 404 -- the ticker/kind/query hit a real endpoint that has no data
    for it right now (e.g. a contract that isn't currently listed), not a bug in this
    client. Distinct from a generic HTTPError so the CLI can print a clear, specific
    message instead of raw requests exception text."""


def _to_float(value) -> Optional[float]:
    """Predictions API numeric fields (yes/no/chance/payout_per_100) are
    returned as strings (e.g. "0.58") -- convert defensively, never raise."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Contract:
    id: str
    symbol: str
    title: str
    status: str
    yes_price: Optional[float]
    no_price: Optional[float]
    chance_pct: Optional[float]
    payout_per_100: Optional[float]
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class PredictionEvent:
    id: str
    title: str
    kind: str
    contracts: list = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class ContractPrice:
    ticker: str
    title: str = ""
    status: str = ""
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    probability_pct: Optional[float] = None
    spread: Optional[float] = None
    raw: dict = field(default_factory=dict, repr=False)


class PredictionsClient:
    def __init__(
        self,
        api_key: str = "",
        base_url: str = PREDICTIONS_API_BASE,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self._base_url}{path}"
        resp = requests.get(url, params=params or {}, headers=self._headers(), timeout=self._timeout)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "unknown")
            raise PredictionsRateLimited(
                f"Rate limited by the Crypto.com Predictions API -- retry after {retry_after}s "
                "(anonymous access is capped at 100 req/min / 50,000 req/day per IP)."
            )
        if resp.status_code == 404:
            raise PredictionsNotFound(
                f"Nothing found at {url} -- if this was a contract ticker, it's not a "
                "real one. Contract tickers are the long `symbol` values nested inside "
                "each event's `contracts` list (e.g. "
                "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO), not short asset "
                "codes like BTC-YES -- get a real one from --predictions or "
                "--predictions-search first."
            )
        resp.raise_for_status()
        return resp.json()

    def list_events(self, kind: Optional[str] = None, limit: int = 20) -> list[PredictionEvent]:
        params: dict = {"limit": limit}
        if kind:
            params["kind"] = kind
        data = self._get("/events", params=params)
        return [_parse_event(row) for row in data.get("data", [])]

    def search_events(self, query: str, limit: int = 20) -> list[PredictionEvent]:
        data = self._get("/events/search", params={"q": query, "limit": limit})
        return [_parse_event(row) for row in data.get("data", [])]

    def get_contract_price(self, ticker: str) -> ContractPrice:
        data = self._get(f"/contracts/{ticker}/price")
        return _parse_contract_price(ticker, data)


def _parse_contract(row: dict) -> Contract:
    return Contract(
        id=str(row.get("id", "")),
        symbol=row.get("symbol", ""),
        title=row.get("title", "(untitled)"),
        status=row.get("status", "?"),
        yes_price=_to_float(row.get("yes")),
        no_price=_to_float(row.get("no")),
        chance_pct=_to_float(row.get("chance")),
        payout_per_100=_to_float(row.get("payout_per_100")),
        raw=row,
    )


def _parse_event(row: dict) -> PredictionEvent:
    contracts = [_parse_contract(c) for c in row.get("contracts", [])]
    return PredictionEvent(
        id=str(row.get("id", "")),
        title=row.get("title", "(untitled)"),
        kind=row.get("kind", "?"),
        contracts=contracts,
        raw=row,
    )


def _parse_contract_price(ticker: str, data: dict) -> ContractPrice:
    # The response may be wrapped in {"data": {...}} like the events
    # endpoints, or returned flat -- handle both.
    payload = data.get("data", data) if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    # Confirmed field names for this endpoint (order-book style, distinct
    # from the yes/no/chance shape nested in /events -- see module docstring).
    return ContractPrice(
        ticker=ticker,
        title=payload.get("title", ""),
        status=payload.get("status", ""),
        bid=_to_float(payload.get("bid")),
        ask=_to_float(payload.get("ask")),
        mid=_to_float(payload.get("mid")),
        probability_pct=_to_float(payload.get("probability")),
        spread=_to_float(payload.get("spread")),
        raw=data,
    )


def format_events(title: str, events: list[PredictionEvent]) -> str:
    bar = "-" * 49
    lines = [bar, title.center(49), bar]
    if not events:
        lines.append("(no events returned)")
    for ev in events:
        lines.append(f"[{ev.kind:<10}] {ev.title}")
        for c in ev.contracts:
            yes_str = f"{c.yes_price:.2f}" if c.yes_price is not None else "?"
            no_str = f"{c.no_price:.2f}" if c.no_price is not None else "?"
            lines.append(f"    {c.title:<18} YES {yes_str}  NO {no_str}")
            lines.append(f"      symbol={c.symbol}")
    lines.append(bar)
    return "\n".join(lines)


def format_contract_price(price: ContractPrice) -> str:
    bar = "-" * 49
    lines = [bar, f"CONTRACT — {price.ticker}".center(49), bar]
    if price.title:
        lines.append(f"Title:               {price.title}")
    if price.status:
        lines.append(f"Status:              {price.status}")
    if price.probability_pct is not None:
        lines.append(f"Probability:         {price.probability_pct:.2f}%")
    if price.bid is not None:
        lines.append(f"Bid:                 {price.bid}")
    if price.ask is not None:
        lines.append(f"Ask:                 {price.ask}")
    if price.mid is not None:
        lines.append(f"Mid:                 {price.mid}")
    if price.spread is not None:
        lines.append(f"Spread:              {price.spread}")
    if all(v is None for v in (price.bid, price.ask, price.mid, price.probability_pct)):
        lines.append("(price fields not found in response -- see .raw)")
        lines.append(str(price.raw))
    lines.append(bar)
    return "\n".join(lines)
