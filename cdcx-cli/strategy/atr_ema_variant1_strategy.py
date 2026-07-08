"""backtrader Strategy built on the ATR_EMA_VARIANT1 indicator.

Mirrors the Pine Script's intent ("Take Profit signal"): treat a support
touch as a long entry and a resistance touch as the take-profit exit.
"""
import backtrader as bt

from indicators.atr_ema_variant1 import ATREMAVariant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH


class ATREMAVariant1Strategy(bt.Strategy):
    params = (
        ("ema_period", DEFAULT_EMA_LENGTH),
        ("atr_period", DEFAULT_ATR_LENGTH),
        ("sr_length", DEFAULT_SR_LENGTH),
        ("stake", None),
    )

    def __init__(self):
        self.signal = ATREMAVariant1(
            self.data,
            ema_period=self.p.ema_period,
            atr_period=self.p.atr_period,
            sr_length=self.p.sr_length,
        )

    def next(self):
        if not self.position:
            if self.signal.support_hit[0]:
                size = self.p.stake if self.p.stake else None
                self.buy(size=size)
        else:
            if self.signal.resistance_hit[0]:
                self.close()

    def notify_order(self, order):
        if order.status in (order.Completed,):
            side = "BUY" if order.isbuy() else "SELL"
            self.log(f"{side} EXECUTED, price={order.executed.price:.4f}, size={order.executed.size}")

    def log(self, message):
        dt = self.datas[0].datetime.date(0)
        print(f"{dt.isoformat()} {message}")
