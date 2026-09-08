import csv
import os

import pytest

from cdcx.config import settings
from cdcx import journal, tax_export

DAY = 86400.0


@pytest.fixture(autouse=True)
def isolated_journal_dir(tmp_path):
    original = settings.trading_journal_dir
    settings.trading_journal_dir = str(tmp_path / "trading")
    yield
    settings.trading_journal_dir = original


def _record_short_term_win():
    # held 10 days
    journal.write_live_result(
        symbol="BTC/USDT", direction="long", quantity=0.1,
        entry_price=60000.0, exit_price=65000.0,
        opened_at=1_700_000_000.0, closed_at=1_700_000_000.0 + 10 * DAY,
        fees=5.0, notes="short-term win",
    )


def _record_long_term_loss():
    # held 400 days
    journal.write_live_result(
        symbol="ETH/USDT", direction="short", quantity=1.0,
        entry_price=3000.0, exit_price=3200.0,
        opened_at=1_700_000_000.0, closed_at=1_700_000_000.0 + 400 * DAY,
        fees=2.0, notes="long-term loss",
    )


def test_load_closed_trades_empty():
    assert tax_export.load_closed_trades() == []


def test_holding_period_and_term_classification():
    _record_short_term_win()
    _record_long_term_loss()
    trades = tax_export.load_closed_trades()
    by_symbol = {t.symbol: t for t in trades}

    assert by_symbol["BTC/USDT"].term == "Short-term"
    assert by_symbol["BTC/USDT"].holding_days == 10
    assert by_symbol["ETH/USDT"].term == "Long-term"
    assert by_symbol["ETH/USDT"].holding_days == 400


def test_realized_pnl_matches_journal():
    _record_short_term_win()
    trade = tax_export.load_closed_trades()[0]
    # (65000 - 60000) * 0.1 - 5 fee = 495
    assert trade.realized_pnl == pytest.approx(495.0)


def test_schedule_d_summary_splits_short_and_long_term():
    _record_short_term_win()
    _record_long_term_loss()
    trades = tax_export.load_closed_trades()
    summary = tax_export.build_schedule_d_summary(trades)

    assert summary["short_term_count"] == 1
    assert summary["long_term_count"] == 1
    assert summary["short_term_gain"] == pytest.approx(495.0)
    # short direction: (exit - entry) * qty * -1 - fees = (3200-3000)*1*-1 - 2 = -202
    assert summary["long_term_gain"] == pytest.approx(-202.0)
    assert summary["total_gain"] == pytest.approx(495.0 - 202.0)


def test_form_8949_csv_has_expected_columns_and_rows():
    _record_short_term_win()
    _record_long_term_loss()
    trades = tax_export.load_closed_trades()
    path = os.path.join(str(settings.trading_journal_dir), "form_8949_test.csv")
    tax_export.write_form_8949_csv(trades, path)

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert set(rows[0].keys()) == {
        "Description", "Date Acquired", "Date Sold", "Proceeds", "Cost Basis", "Gain/Loss", "Term",
    }
    terms = {r["Term"] for r in rows}
    assert terms == {"Short-term", "Long-term"}


def test_cpa_summary_reports_no_trades_message_when_empty():
    assert "No closed live trades" in tax_export.format_cpa_summary([])


def test_ssa_record_includes_disclaimer_and_not_a_filing_notice():
    text = tax_export.format_ssa_record([])
    assert "NOT AN SSA FILING" in text
    assert "NOT TAX ADVICE" in text


def test_export_all_writes_all_four_files():
    _record_short_term_win()
    paths = tax_export.export_all()

    assert set(paths.keys()) == {"form_8949_csv", "schedule_d_summary", "cpa_summary", "ssa_record"}
    for path in paths.values():
        assert os.path.exists(path)

    assert "tax_records" in paths["form_8949_csv"]
    assert "ssa_records" in paths["ssa_record"]
