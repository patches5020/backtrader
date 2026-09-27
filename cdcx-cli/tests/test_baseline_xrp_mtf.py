"""
Baseline regression: XRP/USD 1W/1D/4H/1H, frozen 2026-09-26 ~7:50 PM CDT.

Replays a real Crypto.com OHLCV snapshot (tests/fixtures/xrp_usd_mtf_baseline.json,
captured with tests/fixtures/capture_mtf_snapshot.py) through the unchanged
engine + cdcx-ai CLI, and pins the verdict the regime/confluence gates
produced for it:

    1W  TRENDING (bullish)          -- the only confluence-eligible timeframe
    1D  TRANSITIONAL (bullish lean)
    4H  TRANSITIONAL (bearish lean)
    1H  TRANSITIONAL (bearish lean)
    confluence 1/4 (need 2)  ->  NO TRADE, no paper trade opened

New features (volume profile / Trader Dale concepts, etc.) are meant to
layer ON TOP of these gates, not replace them. If one of these tests starts
failing, a change has altered the baseline decision path or the risk model
-- that needs to be a deliberate, reviewed decision, not a side effect.
"""
from __future__ import annotations

import json
import os
import types

import pytest

from cdcx import cli, engine, journal, trade_manager, vp_bos
from cdcx.config import settings
from cdcx.exchange.cryptocom import CryptoComExchange, OHLCV

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "xrp_usd_mtf_baseline.json")
TIMEFRAMES = ("1w", "1d", "4h", "1h")

with open(FIXTURE) as _fh:
    SNAPSHOT = json.load(_fh)


@pytest.fixture(autouse=True)
def replay_snapshot(monkeypatch, tmp_path):
    """Serve every Crypto.com OHLCV request from the frozen snapshot, pin
    engine.py's clock to the capture moment (its forming-candle check reads
    time.time()), and isolate trade state + journal writes."""

    def fake_fetch(self, symbol, timeframe="1h", limit=200):
        bars = SNAPSHOT["timeframes"][timeframe]
        return OHLCV(**{key: values[-limit:] for key, values in bars.items()})

    monkeypatch.setattr(CryptoComExchange, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(CryptoComExchange, "fetch_ohlcv", fake_fetch)
    frozen_clock = types.SimpleNamespace(time=lambda: SNAPSHOT["captured_at"])
    monkeypatch.setattr(engine, "time", frozen_clock)
    monkeypatch.setattr(vp_bos, "time", frozen_clock)
    monkeypatch.setattr(settings, "trade_state_path", str(tmp_path / "trades.json"))
    monkeypatch.setattr(settings, "trading_journal_dir", str(tmp_path / "journal"))


def _signals():
    return {
        tf: engine.analyze(symbol=SNAPSHOT["symbol"], timeframe=tf, limit=SNAPSHOT["limit"])
        for tf in TIMEFRAMES
    }


def test_regime_per_timeframe_matches_baseline():
    regimes = {tf: sig.regime.regime for tf, sig in _signals().items()}
    assert regimes == {"1w": "trending", "1d": "transitional", "4h": "transitional", "1h": "transitional"}


def test_summary_columns_match_baseline():
    rows = {
        tf: (cli._market_bias(sig), cli._ema_bias(sig), cli._fvg_bias(sig), sig.signal)
        for tf, sig in _signals().items()
    }
    assert rows == {
        "1w": ("bullish", "bullish", "bullish", "BUY"),
        "1d": ("bullish", "bullish", "bullish", "STRONG BUY"),
        "4h": ("bearish", "bearish", "bearish", "STRONG SELL"),
        "1h": ("bearish", "bearish", "bearish", "STRONG SELL"),
    }


def test_no_trade_is_insufficient_confirmation_not_bearish():
    # NO TRADE on a transitional timeframe must carry no direction: the 1D
    # is NO TRADE while its own bias is maximally bullish, so NO TRADE
    # can't be standing in for "sell".
    signals = _signals()
    for tf in ("1d", "4h", "1h"):
        assert signals[tf].execution_signal == "NO TRADE"
    assert signals["1d"].direction_score > 0
    assert signals["1w"].execution_signal == "BUY"


def test_risk_model_is_unchanged():
    # 1.5x ATR stop, stop on the losing side of entry, 1 : 2.2 R:R.
    for tf, sig in _signals().items():
        stop_distance = abs(sig.entry - sig.stop_loss)
        assert stop_distance == pytest.approx(1.5 * sig.atr, rel=1e-3), tf
        assert sig.risk_reward_ratio == pytest.approx(2.2, abs=0.05), tf


def test_cdcx_ai_execute_blocks_on_confluence_and_opens_nothing(capsys):
    # End to end: `cdcx-ai --symbol XRP/USD --timeframes 1w,1d,4h,1h
    # --structure --execute --balance 1000`. Only the 1W is eligible, so
    # confluence must refuse -- even though 1W ATR is expanding (ATR is a
    # confirmation component, never a standalone trigger).
    exit_code = cli.main([
        "--symbol", SNAPSHOT["symbol"], "--timeframes", ",".join(TIMEFRAMES),
        "--structure", "--execute", "--balance", "1000",
    ])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "got 1, need at least 2" in captured.err
    assert "SETUP: NO TRADE" in captured.out
    assert "VP-BOS CONFLUENCE: bull 0/4, bear 0/4" in captured.out
    assert trade_manager.load_trades() == []
    rejected = journal.load_stage("rejected")
    assert [r.get("rejected_at_stage") for r in rejected] == ["confluence"]


def test_vp_bos_layer_matches_baseline():
    # Advisory VP-BOS read of the same snapshot: the 1D and 4H bearish
    # breaks were rejected (closed back through), 1W/1H had no closed break.
    by_tf = vp_bos.build_vp_bos_by_tf(
        {tf: OHLCV(**bars) for tf, bars in SNAPSHOT["timeframes"].items()}, now=SNAPSHOT["captured_at"],
    )
    assert {tf: (r.signal, r.vp) for tf, r in by_tf.items()} == {
        "1w": ("NONE", "--"),
        "1d": ("BOS-FAILED", "REJECT"),
        "4h": ("BOS-FAILED", "REJECT"),
        "1h": ("NONE", "--"),
    }
