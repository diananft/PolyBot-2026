"""Core data models shared across every layer of the bot.

These are intentionally plain dataclasses with no I/O so that the strategy,
risk, sizing and backtest layers stay pure and trivially testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    """Which outcome of a binary Polymarket contract we are taking."""

    UP = "UP"      # "Yes" / price-will-be-higher token
    DOWN = "DOWN"  # "No"  / price-will-be-lower token


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class PricePoint:
    """A single observation of the underlying asset (e.g. BTC on Binance)."""

    symbol: str
    price: float
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class MarketQuote:
    """Best bid/ask for one side of a Polymarket binary market.

    Prices are in probability units in [0, 1] (Polymarket convention: a share
    that pays $1 on resolution).
    """

    market_id: str
    side: Side
    best_bid: float
    best_ask: float
    ts: float = field(default_factory=time.time)

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid


@dataclass(frozen=True)
class Market:
    """A short-duration crypto up/down market on Polymarket."""

    market_id: str
    question: str
    underlying: str          # e.g. "BTCUSDT"
    open_ts: float
    close_ts: float          # resolution time
    open_price: float        # underlying price when the window opened
    up_token_id: str = ""
    down_token_id: str = ""

    @property
    def seconds_to_close(self) -> float:
        return self.close_ts - time.time()

    def fraction_elapsed(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        total = self.close_ts - self.open_ts
        if total <= 0:
            return 1.0
        return max(0.0, min(1.0, (now - self.open_ts) / total))


@dataclass(frozen=True)
class Signal:
    """Output of the strategy layer: an assessment of edge on a market."""

    market_id: str
    side: Side
    fair_prob: float          # model's estimate of P(side resolves true)
    market_prob: float        # what Polymarket currently prices the side at
    edge: float               # fair_prob - market_prob (positive == favourable)
    confidence: float         # [0, 1] model confidence in fair_prob
    rationale: str = ""
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Order:
    market_id: str
    side: Side
    action: Action
    size_usd: float
    limit_price: float
    token_id: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class Fill:
    order: Order
    fill_price: float
    size_usd: float
    fee_usd: float
    ts: float = field(default_factory=time.time)

    @property
    def shares(self) -> float:
        return self.size_usd / self.fill_price if self.fill_price > 0 else 0.0


@dataclass
class Position:
    market_id: str
    side: Side
    shares: float = 0.0
    cost_usd: float = 0.0      # total USD paid for the shares held

    @property
    def avg_price(self) -> float:
        return self.cost_usd / self.shares if self.shares > 0 else 0.0
