import json
import os

import pytest

from cdcx.config import settings
from cdcx import journal


@pytest.fixture(autouse=True)
def isolated_journal_dir(tmp_path):
    """Point journal.py at a throwaway trading/ tree per test."""
    original = settings.trading_journal_dir
    settings.trading_journal_dir = str(tmp_path / "trading")
    yield
    settings.trading_journal_dir = original


def test_ensure_directories_creates_full_tree():
    journal.ensure_directories()
    for stage in journal._STAGE_DIRS:
        assert os.path.isdir(journal.stage_dir(stage))

    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "paper", "signals"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "paper", "simulated_orders"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "paper", "simulated_results"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "paper", "rejected"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "live", "approved"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "live", "orders"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "live", "executions"))
    assert os.path.isdir(os.path.join(settings.trading_journal_dir, "live", "results"))


def test_write_signal_creates_readable_json():
    path = journal.write_signal("BTC/USDT", "1h", {"signal": "STRONG BUY", "entry": 65000.0})
    assert os.path.exists(path)
    with open(path) as f:
        record = json.load(f)
    assert record["stage"] == "signal"
    assert record["symbol"] == "BTC/USDT"
    assert record["timeframe"] == "1h"
    assert record["signal"]["signal"] == "STRONG BUY"
    assert "written_at" in record and "schema_version" in record


def test_write_rejected_and_load_stage_roundtrip():
    journal.write_rejected("ETH/USDT", "no_trade_filter", "R:R below 2:1", {"rr": 1.5})
    journal.write_rejected("ETH/USDT", "regime", "transitional")

    records = journal.load_stage("rejected")
    assert len(records) == 2
    assert {r["rejected_at_stage"] for r in records} == {"no_trade_filter", "regime"}
    assert records[0]["symbol"] == "ETH/USDT"


def test_symbol_with_slash_is_sanitized_in_filename():
    path = journal.write_simulated_order("BTC/USDT", "long", {"entry_price": 65000.0}, [66000.0])
    filename = os.path.basename(path)
    assert "/" not in filename
    assert "BTC-USDT" in filename


def test_write_live_result_computes_pnl():
    path = journal.write_live_result(
        symbol="BTC/USDT", direction="long", quantity=0.1,
        entry_price=60000.0, exit_price=65000.0,
        opened_at=1_700_000_000.0, closed_at=1_700_100_000.0,
        fees=5.0,
    )
    with open(path) as f:
        record = json.load(f)
    assert record["gross_pnl"] == pytest.approx(500.0)
    assert record["realized_pnl"] == pytest.approx(495.0)


def test_load_stage_empty_when_directory_missing():
    assert journal.load_stage("signal") == []
