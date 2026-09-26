"""
volume_profile package
------------------------
FVP (Fixed Volume Profile) intelligence layer -- Phase 1.

INFORMATION ONLY. Nothing in this package is consulted by the entry
checklist, confluence, regime gate, or execution/sizing logic. See
fvp_analysis.py's module docstring for the full scope statement.

Reuses cdcx.indicators.volume_profile_fixed / volume_profile_anchor's
existing POC/VAH/VAL math as-is -- no volume-profile calculation is
reimplemented here. This package only adds zone *state* (tested/untested,
lifecycle) on top of those existing results.
"""
