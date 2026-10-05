"""
Keep the test suite out of the real on-disk records.

settings.trading_journal_dir defaults to the relative "trading", so any test
that reached cdcx.journal without overriding it wrote fixture trades (e.g. a
$65,000 BTC/USDT "simulated order") into the real cdcx-cli/trading/paper/ --
seen 2026-10-04 as 486 junk BTC-USDT files, +11 per full run. Every test now
starts with the journal and the paper-trade log pointed at its own tmp_path;
tests that set their own paths still override this.
"""
import pytest

from cdcx.config import settings


@pytest.fixture(autouse=True)
def _isolate_on_disk_records(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "trading_journal_dir", str(tmp_path / "trading"))
    monkeypatch.setattr(settings, "trade_state_path", str(tmp_path / "cdcx_trades.json"))
