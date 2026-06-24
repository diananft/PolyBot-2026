"""The core latency-arbitrage strategy.

It compares the fair value implied by the fast Binance feed against what
Polymarket currently shows, and emits a Signal when the gap is favourable and
the timing filters pass. It does NOT size or risk-check the trade — that is the
job of the Kelly sizer and the RiskManager, kept separate on purpose.
"""

from __future__ import annotations

import time
from typing import Optional

from ..config import StrategyConfig
from ..models import Market, MarketQuote, PricePoint, Side, Signal
from . import fair_value


class LatencyArbStrategy:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()

    def evaluate(
        self,
        market: Market,
        price: PricePoint,
        up_quote: MarketQuote,
        down_quote: MarketQuote,
        now: float | None = None,
    ) -> Optional[Signal]:
        """Return the best favourable Signal for this market, or None.

        We look at both sides, compute the fair probability from the fast feed,
        compare against the price we'd actually *pay* (the ask, including the
        spread we have to cross), and pick the side with the larger positive
        edge.
        """
        now = now if now is not None else time.time()
        seconds_to_close = market.close_ts - now
        frac = market.fraction_elapsed(now)

        # Timing filters: too early == genuinely uncertain; too late == can't
        # execute/settle cleanly.
        if frac < self.config.min_fraction_elapsed:
            return None
        if seconds_to_close < self.config.min_seconds_to_close:
            return None

        p_up = fair_value.up_probability(
            open_price=market.open_price,
            current_price=price.price,
            seconds_to_close=seconds_to_close,
            minute_vol=self.config.minute_vol,
        )
        confidence = fair_value.confidence_from_inputs(seconds_to_close, frac)

        candidates = []
        for side, fair, quote in (
            (Side.UP, p_up, up_quote),
            (Side.DOWN, 1.0 - p_up, down_quote),
        ):
            # We must pay the ask to take the position.
            market_price = quote.best_ask
            if market_price <= 0 or market_price >= 1:
                continue
            edge = fair - market_price
            candidates.append(
                Signal(
                    market_id=market.market_id,
                    side=side,
                    fair_prob=fair,
                    market_prob=market_price,
                    edge=edge,
                    confidence=confidence,
                    rationale=(
                        f"underlying={price.price:.2f} open={market.open_price:.2f} "
                        f"frac_elapsed={frac:.2f} ttc={seconds_to_close:.0f}s "
                        f"fair={fair:.3f} ask={market_price:.3f} edge={edge:+.3f}"
                    ),
                    ts=now,
                )
            )

        if not candidates:
            return None
        best = max(candidates, key=lambda s: s.edge)
        return best if best.edge > 0 else None
