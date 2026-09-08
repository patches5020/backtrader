"""
Integration coverage for the final NO-TRADE gate wired into
cli._handle_live_order (cdcx/no_trade_gate.py) -- confirms it actually
blocks send_bracket_live from being called when any condition fails, and
allows it through only when everything passes, including the human's typed
confirmation.
"""

from types import SimpleNamespace

import pytest

from cdcx.config import settings
from cdcx import cli, journal
from cdcx import live_execution
from cdcx.live_execution import BracketResult


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    original_journal_dir = settings.trading_journal_dir
    original_trade_state = settings.trade_state_path
    settings.trading_journal_dir = str(tmp_path / "trading")
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trading_journal_dir = original_journal_dir
    settings.trade_state_path = original_trade_state


def _fake_plan(risk_pct=2.0):
    return SimpleNamespace(
        position_size=0.1, stop_price=63000.0, risk_pct=risk_pct,
        entry_price=65000.0, atr_multiplier=1.5,
    )


def _fake_entry_signal(computed_at=None):
    import time
    return SimpleNamespace(computed_at=computed_at if computed_at is not None else time.time(), timeframe="1h")


def _successful_dry_run(order_list):
    return BracketResult(
        order_list=order_list, dry_run_command=["cdcx", "advanced", "create-otoco", "--dry-run"],
        dry_run_returncode=0, dry_run_stdout="ok",
    )


def _call_handle_live_order(monkeypatch, typed_input, plan=None, entry_signal=None, **kwargs):
    monkeypatch.setattr(live_execution, "preview_bracket", lambda order_list: _successful_dry_run(order_list))
    sent = {"called": False}

    def fake_send(result):
        sent["called"] = True
        result.sent_live = True
        result.live_returncode = 0
        result.live_command = ["cdcx", "advanced", "create-otoco"]
        return result

    monkeypatch.setattr(live_execution, "send_bracket_live", fake_send)
    monkeypatch.setattr("builtins.input", lambda *_: typed_input)

    cli._handle_live_order(
        "BTC/USDT", "long", plan or _fake_plan(), [66000.0, 67000.0, 68000.0, 69000.0],
        None, entry_signal=entry_signal or _fake_entry_signal(), **kwargs,
    )
    return sent["called"]


def test_gate_allows_send_when_everything_passes(monkeypatch):
    sent = _call_handle_live_order(
        monkeypatch, "YES", timeframe_confirmed=True, confirmed_no_withdraw_permission=True,
    )
    assert sent is True


def test_gate_blocks_when_human_declines(monkeypatch):
    sent = _call_handle_live_order(
        monkeypatch, "no", timeframe_confirmed=True, confirmed_no_withdraw_permission=True,
    )
    assert sent is False


def test_gate_blocks_when_withdraw_permission_not_confirmed(monkeypatch):
    """Even a full YES doesn't help without the withdrawal-permission attestation --
    this project cannot verify it automatically, so it fails closed."""
    sent = _call_handle_live_order(
        monkeypatch, "YES", timeframe_confirmed=True, confirmed_no_withdraw_permission=False,
    )
    assert sent is False


def test_gate_blocks_when_timeframe_not_confirmed(monkeypatch):
    sent = _call_handle_live_order(
        monkeypatch, "YES", timeframe_confirmed=False, confirmed_no_withdraw_permission=True,
    )
    assert sent is False


def test_gate_blocks_when_risk_exceeds_ceiling(monkeypatch):
    sent = _call_handle_live_order(
        monkeypatch, "YES", plan=_fake_plan(risk_pct=5.0),
        timeframe_confirmed=True, confirmed_no_withdraw_permission=True,
    )
    assert sent is False


def test_gate_blocks_on_stale_market_data(monkeypatch):
    import time
    stale_signal = _fake_entry_signal(computed_at=time.time() - 100_000)  # way older than 3 bars of 1h
    sent = _call_handle_live_order(
        monkeypatch, "YES", entry_signal=stale_signal,
        timeframe_confirmed=True, confirmed_no_withdraw_permission=True,
    )
    assert sent is False


def test_gate_blocks_on_duplicate_recent_live_order(monkeypatch):
    # Simulate a live execution having already gone out for this symbol moments ago.
    journal.write_live_execution("BTC/USDT", {"live_returncode": 0})
    sent = _call_handle_live_order(
        monkeypatch, "YES", timeframe_confirmed=True, confirmed_no_withdraw_permission=True,
    )
    assert sent is False


def test_blocked_gate_is_journaled_with_every_reason(monkeypatch):
    sent = _call_handle_live_order(
        monkeypatch, "no", timeframe_confirmed=False, confirmed_no_withdraw_permission=False,
    )
    assert sent is False

    rejected = journal.load_stage("rejected")
    assert len(rejected) == 1
    record = rejected[0]
    assert record["rejected_at_stage"] == "no_trade_gate"
    assert "Human approval" in record["reason"]
    assert "withdraw" in record["reason"].lower()
    assert "timeframe" in record["reason"].lower()
