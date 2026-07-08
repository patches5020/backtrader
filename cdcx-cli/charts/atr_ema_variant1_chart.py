"""Chart rendering for ATR_EMA_VARIANT1, mirroring the Pine Script's plots:
close price, EMA, support/resistance bands, and support/resistance hit markers.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from indicators.atr_ema_variant1 import compute_atr_ema_variant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH


def plot_atr_ema_variant1(df, output_path, ema_length=DEFAULT_EMA_LENGTH, atr_length=DEFAULT_ATR_LENGTH,
                           sr_length=DEFAULT_SR_LENGTH, title=None):
    """Render the chart to `output_path` (e.g. "chart.png") and return the path."""
    signal = compute_atr_ema_variant1(df, ema_length=ema_length, atr_length=atr_length, sr_length=sr_length)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df.index, df["close"], label="Close", color="#d0d0d0", linewidth=1)
    ax.plot(signal.index, signal["ema"], label="EMA", color="#ff9900", linewidth=1.5)
    ax.plot(signal.index, signal["support"], label="Support", color="#4caf4f", linewidth=1.5)
    ax.plot(signal.index, signal["resistance"], label="Resistance", color="#ff5252", linewidth=1.5)

    support_hits = signal[signal["support_hit"]]
    resistance_hits = signal[signal["resistance_hit"]]
    ax.scatter(support_hits.index, df.loc[support_hits.index, "low"],
               marker="x", color="lime", s=30, label="Support Hit", zorder=5)
    ax.scatter(resistance_hits.index, df.loc[resistance_hits.index, "high"],
               marker="x", color="red", s=30, label="Resistance Hit", zorder=5)

    ax.set_title(title or "EMA+ ATR Support/Resistance Take Profit signal")
    ax.legend(loc="best")
    ax.grid(alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path
