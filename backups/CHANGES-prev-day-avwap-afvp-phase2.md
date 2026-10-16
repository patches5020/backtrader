# Previous-day AVWAP + AFVP, Phase 2: calculations (2026-10-16) -- commit fe57e3c

Analysis only. Not wired into any report, gate, checklist, sizing, watcher or execution path.
No protected parameter changed.

## User decisions (2026-10-16)
Variant A (previous completed day only, frozen) | VWAP matches TradingView (source ohlc4, volume-weighted
stdev bands 1/2/3) | equities regular hours only | crypto profile from 5m (or 15m) bars.

## Files
- `cdcx/indicators/anchored_vwap.py` -- VWAP = sum(p*v)/sum(v); sigma = sqrt(sum(v*p^2)/sum(v) - VWAP^2);
  bands VWAP +/- k*sigma. Sources ohlc4 (default), hlcc4, hlc3, close. None when history doesn't reach the
  anchor or volume is zero.
- `cdcx/volume_profile/prev_day.py` -- previous UTC day (crypto) or last completed 09:30-16:00 ET session
  (equity, DST-correct). Profile from `volume_profile_fixed` unchanged (70% VA, 24 buckets), frozen. VWAP from
  the session open through the last CLOSED bar. UNKNOWN on missing bars, stale 24x7 feed, unfinished day.

## Verification
TradingView XRP/USD 1H AVWAP (anchor 2026-10-14 00:00Z, ohlc4): VWAP 1.319485 / sigma 0.015155; cdcx
1.319486 / 0.015153. Live 5m prev-day (Oct 15): POC 1.3077 VAH 1.3263 VAL 1.2944; AVWAP 1.3196 sigma 0.0160.

## Tests
690 passed (20 new: test_anchored_vwap.py, test_prev_day_levels.py); handoff validation PASS.
Known gap: equity half-days read as missing bars (UNKNOWN).
