"""Kelly-criterion position sizing for binary contracts.

For a binary contract bought at price ``p`` (probability units) that pays $1 on
a win and $0 on a loss, a $1 stake returns:
    * net profit of (1-p)/p per dollar on a win
    * loss of the full dollar on a loss

The Kelly fraction of bankroll to stake is:
    f* = (b*win_prob - loss_prob) / b
where b = (1-p)/p are the net odds, win_prob is our estimated probability the
contract resolves in our favour, and loss_prob = 1 - win_prob.

We deliberately deploy only a *fraction* of full Kelly (default quarter) and
cap the result, because full Kelly is brutal under estimation error — exactly
the "inconsistent sizing" failure mode the article attributes to humans.
"""

from __future__ import annotations


def kelly_fraction(win_prob: float, price: float) -> float:
    """Full-Kelly fraction of bankroll for a binary contract.

    Args:
        win_prob: estimated probability the position resolves in our favour.
        price: entry price in probability units (0, 1).

    Returns the optimal fraction in [0, 1]. Returns 0 for non-positive edge.
    """
    if price <= 0.0 or price >= 1.0:
        return 0.0
    win_prob = max(0.0, min(1.0, win_prob))
    b = (1.0 - price) / price  # net odds received on a win
    loss_prob = 1.0 - win_prob
    f = (b * win_prob - loss_prob) / b
    return max(0.0, f)


def position_size_usd(
    win_prob: float,
    price: float,
    bankroll_usd: float,
    kelly_fraction_used: float,
    max_position_fraction: float,
) -> float:
    """USD to stake after applying fractional Kelly and the per-trade cap."""
    f_star = kelly_fraction(win_prob, price)
    f = f_star * kelly_fraction_used
    f = min(f, max_position_fraction)
    return max(0.0, f * bankroll_usd)
