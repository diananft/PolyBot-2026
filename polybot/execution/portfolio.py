"""Portfolio: tracks cash, open positions and realised/unrealised PnL.

Pure in-memory accounting. The executor feeds it Fills; the engine queries it
for equity and exposure to drive the risk manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Fill, Position, Side


@dataclass
class ClosedTrade:
    market_id: str
    side: Side
    pnl_usd: float


@dataclass
class Portfolio:
    cash_usd: float
    positions: dict[tuple[str, Side], Position] = field(default_factory=dict)
    closed: list[ClosedTrade] = field(default_factory=list)
    fees_paid_usd: float = 0.0

    # --- opening / adding to positions ----------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Apply a buy fill: spend cash, accrue shares."""
        key = (fill.order.market_id, fill.order.side)
        pos = self.positions.get(key) or Position(fill.order.market_id, fill.order.side)
        pos.shares += fill.shares
        pos.cost_usd += fill.size_usd
        self.positions[key] = pos
        self.cash_usd -= (fill.size_usd + fill.fee_usd)
        self.fees_paid_usd += fill.fee_usd

    # --- resolution / closing -------------------------------------------

    def settle(self, market_id: str, won_side: Side) -> float:
        """Settle a resolved market: winning shares pay $1, losers pay $0.

        Returns realised PnL for the market and removes its positions.
        """
        realised = 0.0
        for side in (Side.UP, Side.DOWN):
            key = (market_id, side)
            pos = self.positions.pop(key, None)
            if pos is None:
                continue
            payout = pos.shares if side == won_side else 0.0
            pnl = payout - pos.cost_usd
            realised += pnl
            self.cash_usd += payout
            self.closed.append(ClosedTrade(market_id, side, pnl))
        return realised

    # --- valuation ------------------------------------------------------

    def exposure_usd(self) -> float:
        """Total cost basis tied up in open positions."""
        return sum(p.cost_usd for p in self.positions.values())

    def equity_usd(self, mark_prices: dict[tuple[str, Side], float] | None = None) -> float:
        """Cash plus mark-to-market value of open positions.

        ``mark_prices`` maps (market_id, side) -> current probability price. If
        a position has no mark, its cost basis is used (neutral assumption).
        """
        mark_prices = mark_prices or {}
        value = self.cash_usd
        for key, pos in self.positions.items():
            price = mark_prices.get(key)
            value += pos.shares * price if price is not None else pos.cost_usd
        return value

    @property
    def realised_pnl(self) -> float:
        return sum(t.pnl_usd for t in self.closed)
