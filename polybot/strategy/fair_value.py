"""Fair-value model for short-duration up/down crypto contracts.

This is the price-discovery half of every latency-arbitrage trade. Given:
  * the price of the underlying when the contract window opened,
  * the current price of the underlying on Binance (the fast feed), and
  * how much time is left until the contract resolves,
we estimate the probability that the contract resolves "UP" (price at close
strictly higher than at open).

Model: assume log-returns over the remaining window are approximately
Normal(drift~0, sigma) where sigma scales with sqrt(remaining minutes). The
"UP" outcome requires the final price to exceed the open price, so we need the
remaining return to exceed the *negative* of the move already realised. This is
a closed-form Normal CDF — no dependency on scipy.
"""

from __future__ import annotations

import math

from ..models import Market, PricePoint, Side


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (stdlib only)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def up_probability(
    open_price: float,
    current_price: float,
    seconds_to_close: float,
    minute_vol: float,
) -> float:
    """P(price_at_close > open_price | current_price, time_left).

    Args:
        open_price: underlying price when the contract window opened.
        current_price: latest underlying price (fast Binance feed).
        seconds_to_close: time remaining until resolution.
        minute_vol: stdev of log-return over a 1-minute horizon.
    """
    if open_price <= 0 or current_price <= 0:
        return 0.5

    # Move already realised, in log terms. If positive, we're already above the
    # open and UP is favoured.
    realised = math.log(current_price / open_price)

    # No time left: outcome is essentially determined by the current sign.
    if seconds_to_close <= 0:
        return 1.0 if current_price > open_price else 0.0

    minutes_left = seconds_to_close / 60.0
    sigma = minute_vol * math.sqrt(max(minutes_left, 1e-9))
    if sigma <= 0:
        return 1.0 if current_price > open_price else 0.0

    # We win UP if the *future* log-return R over the remaining window satisfies
    # current_price * e^R > open_price  <=>  R > -realised.
    # R ~ Normal(0, sigma). So P = 1 - Phi(-realised / sigma) = Phi(realised/sigma).
    z = realised / sigma
    return _norm_cdf(z)


def fair_prob_for_side(
    market: Market,
    price: PricePoint,
    side: Side,
    minute_vol: float,
    now: float | None = None,
) -> float:
    """Fair probability that the given side resolves true."""
    import time as _time

    now = now if now is not None else _time.time()
    seconds_to_close = market.close_ts - now
    p_up = up_probability(
        open_price=market.open_price,
        current_price=price.price,
        seconds_to_close=seconds_to_close,
        minute_vol=minute_vol,
    )
    return p_up if side is Side.UP else (1.0 - p_up)


def confidence_from_inputs(seconds_to_close: float, fraction_elapsed: float) -> float:
    """A crude confidence score.

    We are more confident later in the window (less time for the move to
    reverse) but we dampen confidence in the very last seconds where execution
    risk dominates. Range roughly [0, 1].
    """
    # Confidence rises with elapsed fraction.
    base = max(0.0, min(1.0, fraction_elapsed))
    # Penalise the final few seconds (can't get filled / settle cleanly).
    if seconds_to_close < 10:
        base *= 0.5
    return base
