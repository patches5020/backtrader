"""
tax_export.py
--------------
Turns the closed live-trade journal (`trading/live/results/*.json`, written
by `journal.write_live_result()` / `python -m cdcx --record-live-close`)
into paperwork for a CPA, and a documentary trading-activity record for
Social Security purposes.

**This is NOT tax or legal advice.** It mechanically formats numbers you
already recorded. It does not know your cost-basis method (FIFO/LIFO/
specific-ID -- this module assumes each recorded round trip already IS one
lot, i.e. FIFO-per-trade), your jurisdiction, or whether you have elected
any special tax status. Have a CPA review every export before filing
anything with the IRS or relying on it for SSA purposes.

US federal crypto notes baked into the mechanics here (confirm with your
own CPA -- these are the assumptions this module encodes, not guarantees):

    - The IRS treats cryptocurrency as PROPERTY (Notice 2014-21). Each
      closed position is a taxable disposition, reported like a stock sale
      on Form 8949 / Schedule D -- not on Schedule C, by default.
    - Held > 365 days = long-term; <= 365 days = short-term. Computed as
      `closed_at - opened_at` in days, nothing fancier (no wash-sale rules,
      no like-kind exchange treatment -- neither currently applies to crypto
      under US law, but rules change; verify).
    - Ordinary trading gains are capital gains, NOT self-employment income,
      and by default are NOT reported to the Social Security Administration
      as "earnings" on your SSA earnings record. That only changes if you
      have elected IRS Trader Tax Status with a valid Section 475(f)
      mark-to-market election -- a specific, affirmatively elected status,
      not the default for anyone who trades. The SSA export below is a
      documentary record of trading activity only, not a Schedule C / SE-tax
      filing -- ask your CPA whether Trader Tax Status applies to you before
      assuming otherwise.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from . import journal
from .config import settings

LONG_TERM_HOLDING_DAYS = 365


@dataclass
class ClosedTrade:
    symbol: str
    direction: str
    quantity: float
    entry_price: float
    exit_price: float
    opened_at: float
    closed_at: float
    fees: float
    gross_pnl: float
    realized_pnl: float
    notes: str

    @property
    def proceeds(self) -> float:
        """What the position was closed for, gross (before fees)."""
        return self.exit_price * self.quantity

    @property
    def cost_basis(self) -> float:
        """What the position was opened for, gross (before fees), plus fees
        rolled into cost basis (fees reduce gain either way -- simplest to
        add them here rather than track entry/exit fees separately)."""
        return self.entry_price * self.quantity + self.fees

    @property
    def holding_days(self) -> int:
        return max(0, int((self.closed_at - self.opened_at) // 86400))

    @property
    def term(self) -> str:
        return "Long-term" if self.holding_days > LONG_TERM_HOLDING_DAYS else "Short-term"

    def date(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def load_closed_trades() -> list[ClosedTrade]:
    """Reads every record from trading/live/results/, oldest first."""
    records = journal.load_stage("live_result")
    trades = []
    for r in records:
        trades.append(ClosedTrade(
            symbol=r["symbol"],
            direction=r.get("direction", ""),
            quantity=float(r.get("quantity", 0.0)),
            entry_price=float(r.get("entry_price", 0.0)),
            exit_price=float(r.get("exit_price", 0.0)),
            opened_at=float(r.get("opened_at", 0.0)),
            closed_at=float(r.get("closed_at", 0.0)),
            fees=float(r.get("fees", 0.0)),
            gross_pnl=float(r.get("gross_pnl", 0.0)),
            realized_pnl=float(r.get("realized_pnl", 0.0)),
            notes=r.get("notes", ""),
        ))
    return trades


# --- Form 8949 / Schedule D (IRS -- capital gains from property disposition) --

def build_form_8949_rows(trades: list[ClosedTrade]) -> list[dict]:
    rows = []
    for t in trades:
        rows.append({
            "Description": f"{t.quantity} {t.symbol} ({t.direction.upper()})",
            "Date Acquired": t.date(t.opened_at),
            "Date Sold": t.date(t.closed_at),
            "Proceeds": round(t.proceeds, 2),
            "Cost Basis": round(t.cost_basis, 2),
            "Gain/Loss": round(t.realized_pnl, 2),
            "Term": t.term,
        })
    return rows


def write_form_8949_csv(trades: list[ClosedTrade], path: str) -> str:
    rows = build_form_8949_rows(trades)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Description", "Date Acquired", "Date Sold", "Proceeds", "Cost Basis", "Gain/Loss", "Term"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_schedule_d_summary(trades: list[ClosedTrade]) -> dict:
    short_term = [t for t in trades if t.term == "Short-term"]
    long_term = [t for t in trades if t.term == "Long-term"]
    return {
        "short_term_count": len(short_term),
        "short_term_gain": round(sum(t.realized_pnl for t in short_term), 2),
        "long_term_count": len(long_term),
        "long_term_gain": round(sum(t.realized_pnl for t in long_term), 2),
        "total_gain": round(sum(t.realized_pnl for t in trades), 2),
        "total_fees": round(sum(t.fees for t in trades), 2),
    }


def format_schedule_d_summary(trades: list[ClosedTrade]) -> str:
    s = build_schedule_d_summary(trades)
    lines = [
        "=" * 60,
        "SCHEDULE D SUMMARY (short-term / long-term capital gains)".center(60),
        "=" * 60,
        "NOT TAX ADVICE -- have a CPA review before filing.",
        "-" * 60,
        f"Short-term (held <= {LONG_TERM_HOLDING_DAYS} days): {s['short_term_count']} closed trades, "
        f"net gain/loss ${s['short_term_gain']:,.2f}",
        f"Long-term  (held >  {LONG_TERM_HOLDING_DAYS} days): {s['long_term_count']} closed trades, "
        f"net gain/loss ${s['long_term_gain']:,.2f}",
        "-" * 60,
        f"Total net capital gain/loss: ${s['total_gain']:,.2f}",
        f"Total fees paid (already netted into gain/loss above): ${s['total_fees']:,.2f}",
        "=" * 60,
    ]
    return "\n".join(lines)


# --- CPA summary report --------------------------------------------------

def format_cpa_summary(trades: list[ClosedTrade]) -> str:
    if not trades:
        return "No closed live trades recorded in trading/live/results/ yet -- nothing to summarize."

    by_symbol: dict[str, list[ClosedTrade]] = defaultdict(list)
    by_year: dict[int, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)
        year = datetime.fromtimestamp(t.closed_at, tz=timezone.utc).year
        by_year[year].append(t)

    wins = [t for t in trades if t.realized_pnl > 0]
    total_pnl = sum(t.realized_pnl for t in trades)
    total_fees = sum(t.fees for t in trades)

    lines = [
        "=" * 60,
        "CPA SUMMARY -- REALIZED TRADING ACTIVITY".center(60),
        "=" * 60,
        "NOT TAX ADVICE -- mechanically summarizes recorded trades only.",
        "Cost-basis method assumed: one lot per recorded round trip.",
        "-" * 60,
        f"Closed trades:      {len(trades)}",
        f"Win rate:           {round(100 * len(wins) / len(trades), 1)}%",
        f"Total realized P&L: ${total_pnl:,.2f}",
        f"Total fees:         ${total_fees:,.2f}",
        "",
        "By symbol:",
    ]
    for symbol, ts in sorted(by_symbol.items()):
        pnl = sum(t.realized_pnl for t in ts)
        lines.append(f"  {symbol:<12} {len(ts):>4} trades   net P&L ${pnl:,.2f}")

    lines.append("")
    lines.append("By tax year (based on close date, UTC):")
    for year, ts in sorted(by_year.items()):
        pnl = sum(t.realized_pnl for t in ts)
        st = sum(1 for t in ts if t.term == "Short-term")
        lt = sum(1 for t in ts if t.term == "Long-term")
        lines.append(f"  {year}   {len(ts):>4} trades ({st} short-term / {lt} long-term)   net P&L ${pnl:,.2f}")

    lines.append("=" * 60)
    return "\n".join(lines)


# --- SSA documentary record -----------------------------------------------

def format_ssa_record(trades: list[ClosedTrade]) -> str:
    """
    A documentary record of trading activity for your own files -- NOT a
    Social Security earnings filing. Ordinary capital gains from trading do
    not count as "earnings" on your Social Security wage record; that only
    applies if you've elected IRS Trader Tax Status with a Section 475(f)
    mark-to-market election, which converts trading gains/losses to
    ordinary income reported via Schedule C (and does become
    self-employment-adjacent, though even then SE tax on trading gains has
    its own separate rules -- ask your CPA). This export exists so you have
    a clean activity record to hand your CPA/SSA if that determination ever
    comes up -- it does not make that determination itself.
    """
    lines = [
        "=" * 60,
        "SSA DOCUMENTARY TRADING-ACTIVITY RECORD".center(60),
        "=" * 60,
        "NOT AN SSA FILING. NOT TAX ADVICE.",
        "",
        "By default, capital gains from trading are NOT earnings for Social",
        "Security purposes and are not reported to the SSA. This record only",
        "matters if a CPA determines you hold IRS Trader Tax Status with a",
        "Section 475(f) mark-to-market election -- confirm that before using",
        "this for anything beyond your own records.",
        "-" * 60,
    ]
    if not trades:
        lines.append("No closed live trades recorded in trading/live/results/ yet.")
    else:
        total_pnl = sum(t.realized_pnl for t in trades)
        lines.append(f"Closed trades on file: {len(trades)}")
        lines.append(f"Total realized gain/loss: ${total_pnl:,.2f}")
        lines.append("")
        lines.append(f"{'Date Closed':<12} {'Symbol':<10} {'Dir':<6} {'Qty':>10} {'Realized P&L':>14}")
        for t in trades:
            lines.append(
                f"{t.date(t.closed_at):<12} {t.symbol:<10} {t.direction.upper():<6} "
                f"{t.quantity:>10} {t.realized_pnl:>14,.2f}"
            )
    lines.append("=" * 60)
    return "\n".join(lines)


# --- top-level export -----------------------------------------------------

def export_all(generated_at: float | None = None) -> dict[str, str]:
    """
    Writes every export into trading/tax_records/ and trading/ssa_records/
    (siblings of trading/paper/ and trading/live/) and returns the paths
    written. Safe to re-run -- each run is timestamped, nothing is
    overwritten.
    """
    trades = load_closed_trades()
    ts = generated_at if generated_at is not None else datetime.now(tz=timezone.utc).timestamp()
    stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

    root = settings.trading_journal_dir
    tax_dir = os.path.join(root, "tax_records")
    ssa_dir = os.path.join(root, "ssa_records")
    os.makedirs(tax_dir, exist_ok=True)
    os.makedirs(ssa_dir, exist_ok=True)

    paths = {}

    form_8949_path = os.path.join(tax_dir, f"form_8949_{stamp}.csv")
    write_form_8949_csv(trades, form_8949_path)
    paths["form_8949_csv"] = form_8949_path

    schedule_d_path = os.path.join(tax_dir, f"schedule_d_summary_{stamp}.txt")
    with open(schedule_d_path, "w") as f:
        f.write(format_schedule_d_summary(trades))
    paths["schedule_d_summary"] = schedule_d_path

    cpa_path = os.path.join(tax_dir, f"cpa_summary_{stamp}.txt")
    with open(cpa_path, "w") as f:
        f.write(format_cpa_summary(trades))
    paths["cpa_summary"] = cpa_path

    ssa_path = os.path.join(ssa_dir, f"ssa_trading_record_{stamp}.txt")
    with open(ssa_path, "w") as f:
        f.write(format_ssa_record(trades))
    paths["ssa_record"] = ssa_path

    return paths
