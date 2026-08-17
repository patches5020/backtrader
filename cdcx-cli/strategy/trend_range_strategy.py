"""Regime-adaptive strategy: different entries for trending vs ranging
markets, both wired to a single ATR-based stop-loss / take-profit /
risk-to-reward framework.

Built entirely on top of the indicators and parameters already defined in
cdcx-cli:

  - ``indicators.atr_ema_variant1.ATREMAVariant1`` (EMA/ATR support &
    resistance bands, same ``ema_period``/``atr_period``/``sr_length``
    defaults as the existing ``ATREMAVariant1Strategy``)
  - ``indicators.regime.MarketRegime`` (Wilder ADX trend/range classifier)

Regime logic
------------
- **Trending** (``adx >= adx_threshold``): enter long on a breakout above
  the resistance band while price is above the EMA (trend continuation).
- **Ranging** (``adx < adx_threshold``): enter long on a touch of the
  support band (mean reversion), same trigger the base strategy uses.

Both branches feed the same risk model. On entry:

  - ``stop_loss   = entry - atr * atr_sl_mult``
  - ``take_profit = entry + (entry - stop_loss) * risk_reward``
  - ``size`` is chosen so a stop-out risks exactly ``risk_pct`` percent of
    account equity (risk-based position sizing).

Orders are submitted as a single OCO bracket (``buy_bracket``): a market
entry plus a ``Stop`` sell at ``stop_loss`` and a ``Limit`` sell at
``take_profit``, so the configured risk-to-reward ratio is enforced by the
broker rather than by polling on every bar.
"""
import backtrader as bt

from indicators.atr_ema_variant1 import ATREMAVariant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH
from indicators.regime import MarketRegime, DEFAULT_ADX_LENGTH, DEFAULT_TREND_THRESHOLD

DEFAULT_RISK_REWARD = 2.0
DEFAULT_ATR_SL_MULT = 1.5
DEFAULT_RISK_PCT = 1.0


class TrendRangeStrategy(bt.Strategy):
    params = (
        ("ema_period", DEFAULT_EMA_LENGTH),
        ("atr_period", DEFAULT_ATR_LENGTH),
        ("sr_length", DEFAULT_SR_LENGTH),
        ("adx_period", DEFAULT_ADX_LENGTH),
        ("adx_threshold", DEFAULT_TREND_THRESHOLD),
        ("risk_reward", DEFAULT_RISK_REWARD),
        ("atr_sl_mult", DEFAULT_ATR_SL_MULT),
        ("risk_pct", DEFAULT_RISK_PCT),
    )

    def __init__(self):
        self.signal = ATREMAVariant1(
            self.data,
            ema_period=self.p.ema_period,
            atr_period=self.p.atr_period,
            sr_length=self.p.sr_length,
        )
        self.regime = MarketRegime(
            self.data,
            adx_period=self.p.adx_period,
            trend_threshold=self.p.adx_threshold,
        )
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.orefs = []
        self.entry_context = {}

    def next(self):
        if self.orefs:
            return  # a bracket group is already pending/live

        if self.position:
            return

        trending = bool(self.regime.trending[0])
        if trending:
            entry_signal = bool(self.signal.resistance_hit[0]) and self.data.close[0] > self.signal.ema[0]
        else:
            entry_signal = bool(self.signal.support_hit[0])

        if entry_signal:
            self._enter_long(trending)

    def _enter_long(self, trending):
        price = self.data.close[0]
        risk_per_unit = self.atr[0] * self.p.atr_sl_mult
        if not risk_per_unit or risk_per_unit <= 0:
            return

        stop_loss = price - risk_per_unit
        take_profit = price + risk_per_unit * self.p.risk_reward

        size = self._risk_sized_position(price, stop_loss)
        if size <= 0:
            return

        os = self.buy_bracket(
            size=size,
            price=price,
            exectype=bt.Order.Market,
            stopprice=stop_loss,
            limitprice=take_profit,
        )
        self.orefs = [o.ref for o in os]
        self.entry_context[os[0].ref] = {
            "regime": "trend" if trending else "range",
            "entry": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": self.p.risk_reward,
        }

    def _risk_sized_position(self, price, stop_loss):
        """Size the position so a stop-out risks ``risk_pct``% of equity."""
        risk_per_unit = price - stop_loss
        if risk_per_unit <= 0:
            return 0

        equity = self.broker.getvalue()
        risk_amount = equity * (self.p.risk_pct / 100.0)
        size = risk_amount / risk_per_unit

        # Never size past what cash can actually buy.
        cash = self.broker.getcash()
        max_affordable = (cash / price) if price else 0
        size = min(size, max_affordable)
        return max(int(size), 0)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return

        if order.status == order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            ctx = self.entry_context.get(order.ref) or self.entry_context.get(getattr(order.parent, "ref", None))
            extra = ""
            if order.isbuy() and ctx:
                ctx["size"] = order.executed.size
                ctx["fill_price"] = order.executed.price
                extra = (f" regime={ctx['regime']} SL={ctx['stop_loss']:.4f} "
                         f"TP={ctx['take_profit']:.4f} R:R=1:{ctx['risk_reward']:.2f}")
            self.log(f"{side} EXECUTED, price={order.executed.price:.4f}, size={order.executed.size}{extra}")

        if not order.alive() and order.ref in self.orefs:
            self.orefs.remove(order.ref)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE CLOSED, pnl={trade.pnl:.4f}, pnlcomm={trade.pnlcomm:.4f}")

    def log(self, message):
        dt = self.datas[0].datetime.date(0)
        print(f"{dt.isoformat()} {message}")
