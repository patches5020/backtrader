"""Anchored volume profile (v1): volume profile computed from an anchor point to the latest bar.

Thin wrapper around fixed_volume_profile that first slices the DataFrame
from an anchor (a timestamp, index label, or integer position) to the end.
"""
from indicators.fixed_volume_profile import compute_volume_profile


def compute_anchored_volume_profile(df, anchor, bins=24, value_area_pct=0.70):
    """Return the same shape as compute_volume_profile, computed on df[anchor:]."""
    if isinstance(anchor, int):
        sliced = df.iloc[anchor:]
    else:
        sliced = df.loc[anchor:]
    return compute_volume_profile(sliced, bins=bins, value_area_pct=value_area_pct)
