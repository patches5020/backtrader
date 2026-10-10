# VP plans: 1% risk per trade on XRP and XLM (2026-10-10) -- commit 7743a6e

**Protected parameter change, approved by the user** ("1% on XRP, 1% on XLM"): risk per trade lowered from 2% to 1%
for the four VP paper plans (xrp-bull-vp, xrp-bear-vp, xlm-bull-vp, xlm-bear-vp). cdcx's global default stays 2%.

- **Config:** `risk_pct: 1.0` in `xrp_vp_plan_config.json` and `xlm_vp_plan_config.json` (capped at 2.0; 2.0 if absent).
  Used by R3 (cdcx entry checklist), the sizing preview, the PERMISSION NEEDED alert and `--approve`.
- **Open trades:** one per coin (XRP and XLM may each hold one) -> at most 2% total open risk. Approval lock still shared.
- **Verified:** cdcx sizing at 1% = $9.80 on $980 (XRP notional ~$753, XLM ~$1,154); offline 33/33; E2E temp ledger:
  XRP + XLM both open at 1% each, second XRP refused; 664 passed; both watchers restarted, previews show 1%.

Protected params: risk per trade 2% -> 1% for these plans (user-approved). Everything else unchanged.
