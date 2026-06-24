"""Self-contained demo & synthetic data generator.

Generates realistic-but-fake short-duration markets where Polymarket's quote
*lags* the underlying — exactly the structural inefficiency the article
describes. The realised outcome is driven by the same price path the bot sees,
so the demo measures genuine edge, not a rigged win. Fully deterministic given a
seed; requires no network.
"""

from __future__ import annotations

import math
import random

from .backtest.engine import Backtester, BacktestResult, Scenario
from .config import Config
from .models import Market, MarketQuote, PricePoint, Side
from .strategy.fair_value import up_probability


def ticks_ts(open_ts: float, window_s: float, n_ticks: int, idx: int) -> float:
    """Timestamp of tick ``idx`` (matching how ticks are laid out below)."""
    spacing = window_s / n_ticks
    return open_ts + (idx + 1) * spacing


def _simulate_path(open_price: float, minute_vol: float, window_s: float, n_ticks: int, rng: random.Random) -> list[float]:
    """Simulate a discrete GBM-ish log-price path of length n_ticks."""
    dt_min = (window_s / 60.0) / n_ticks
    step_sigma = minute_vol * math.sqrt(dt_min)
    prices = [open_price]
    logp = math.log(open_price)
    for _ in range(n_ticks - 1):
        logp += rng.gauss(0.0, step_sigma)
        prices.append(math.exp(logp))
    return prices


def build_demo_scenarios(n: int = 200, seed: int = 7) -> list[Scenario]:
    """Build ``n`` synthetic 15-minute BTC up/down markets."""
    rng = random.Random(seed)
    cfg = Config()
    minute_vol = cfg.strategy.minute_vol
    window_s = 15 * 60.0
    n_ticks = 30
    base_open_ts = 1_700_000_000.0

    scenarios: list[Scenario] = []
    for i in range(n):
        open_price = 60_000.0 * (1 + rng.uniform(-0.05, 0.05))
        open_ts = base_open_ts + i * window_s
        close_ts = open_ts + window_s
        path = _simulate_path(open_price, minute_vol, window_s, n_ticks, rng)
        close_price = path[-1]

        market = Market(
            market_id=f"demo-{i}",
            question=f"Will BTC be higher at the close of window {i}?",
            underlying="BTCUSDT",
            open_ts=open_ts,
            close_ts=close_ts,
            open_price=open_price,
            up_token_id=f"up-{i}",
            down_token_id=f"down-{i}",
        )

        # Polymarket quote LAGS the underlying by a few ticks. We model the
        # quote as the fair value implied a `lag_ticks` window earlier — so the
        # only edge the bot can capture is the *recent* move that Polymarket has
        # not yet re-priced. This keeps the demo honest: the edge is bounded by
        # the lag, not by freezing the market at 50/50 for the whole window.
        lag_ticks = 1
        decision_idx = int(n_ticks * cfg.strategy.min_fraction_elapsed)
        ref_idx = max(0, decision_idx - lag_ticks)
        ref_ttc = close_ts - ticks_ts(open_ts, window_s, n_ticks, ref_idx)
        stale_up = up_probability(open_price, path[ref_idx], ref_ttc, minute_vol)
        # Competition / adverse selection: other arbitrageurs have *partially*
        # corrected the quote, and sometimes over-corrected past fair. This
        # two-sided noise means many apparent edges are illusory and get
        # filtered out — exactly what makes the live game hard.
        stale_up = min(0.97, max(0.03, stale_up + rng.gauss(0.0, 0.03)))
        half_spread = 0.01
        up_quote = MarketQuote("?", Side.UP, stale_up - half_spread, stale_up + half_spread)
        down_quote = MarketQuote(
            "?", Side.DOWN,
            (1 - stale_up) - half_spread, (1 - stale_up) + half_spread,
        )

        ticks = [
            PricePoint("BTCUSDT", p, ts=open_ts + (j + 1) * (window_s / n_ticks))
            for j, p in enumerate(path)
        ]

        scenarios.append(
            Scenario(
                market=market,
                ticks=ticks,
                quotes={Side.UP: up_quote, Side.DOWN: down_quote},
                close_price=close_price,
            )
        )
    return scenarios


def run_demo(n: int = 200, seed: int = 7, config: Config | None = None) -> BacktestResult:
    scenarios = build_demo_scenarios(n=n, seed=seed)
    return Backtester(config or Config()).run(scenarios)


if __name__ == "__main__":
    res = run_demo()
    print(res)
