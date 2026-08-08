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

Note on the contract-price response shape: the quickstart docs confirm the
events response is `{"data": [...]}` with `title`/`kind` fields per event
(shown directly in the docs' own sample code), but this project's sandbox
cannot reach crypto.com to capture a live `/contracts/{ticker}/price`
response body -- outbound requests to the whole crypto.com domain family
are blocked here. `_parse_contract_price` below is written defensively: it
tries a handful of plausible field names (`yes_price`/`no_price`, or
`last_price`) and always keeps the full raw JSON on `ContractPrice.raw`, so
nothing is lost if the guessed field names don't match. Verify against a
real response on a machine that can reach data-api.crypto.com and adjust
`_parse_contract_price` if the field names differ.
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


@dataclass
class PredictionEvent:
    id: str
    title: str
    kind: str
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class ContractPrice:
    ticker: str
    yes_price: Optional[float]
    no_price: Optional[float]
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
                f"Nothing found at {url} -- if this was a contract ticker, it may not be "
                "listed/live right now (tickers in the docs are illustrative examples, not "
                "guaranteed to exist). Check --predictions for currently active events, or "
                "the crypto.com Predictions site, for a real ticker to try."
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


def _parse_event(row: dict) -> PredictionEvent:
    return PredictionEvent(
        id=str(row.get("id", "")),
        title=row.get("title", "(untitled)"),
        kind=row.get("kind", "?"),
        raw=row,
    )


def _parse_contract_price(ticker: str, data: dict) -> ContractPrice:
    # The response may be wrapped in {"data": {...}} like the events
    # endpoints, or returned flat -- handle both. Field names are a
    # best-effort guess; see the module docstring.
    payload = data.get("data", data) if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    yes_price = payload.get("yes_price", payload.get("yes"))
    no_price = payload.get("no_price", payload.get("no"))
    if yes_price is None and no_price is None:
        # Some binary-market APIs only quote a single "last traded" price
        # for the YES side and imply NO as its complement.
        last_price = payload.get("last_price")
        if last_price is not None:
            yes_price = last_price
            no_price = round(1.0 - float(last_price), 6)

    return ContractPrice(ticker=ticker, yes_price=yes_price, no_price=no_price, raw=data)


def format_events(title: str, events: list[PredictionEvent]) -> str:
    bar = "-" * 49
    lines = [bar, title.center(49), bar]
    if not events:
        lines.append("(no events returned)")
    for ev in events:
        lines.append(f"[{ev.kind:<10}] {ev.title}")
    lines.append(bar)
    return "\n".join(lines)


def format_contract_price(price: ContractPrice) -> str:
    bar = "-" * 49
    lines = [bar, f"CONTRACT — {price.ticker}".center(49), bar]
    if price.yes_price is not None:
        pct = f"{price.yes_price * 100:.1f}%" if price.yes_price <= 1 else str(price.yes_price)
        lines.append(f"YES:                 {price.yes_price}  (implied ~{pct})")
    if price.no_price is not None:
        lines.append(f"NO:                  {price.no_price}")
    if price.yes_price is None and price.no_price is None:
        lines.append("(price fields not found in response -- see .raw)")
        lines.append(str(price.raw))
    lines.append(bar)
    return "\n".join(lines)
