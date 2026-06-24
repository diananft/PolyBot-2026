"""Layer 2 + 6 — orchestration and execution loop.

This is the live/paper trading engine. Each cycle it:
  1. pulls the fast Binance price (Layer 3),
  2. reads the Polymarket quotes for each tracked market (Layer 3),
  3. asks the strategy for an edge signal (strategy),
  4. runs it past the brain (Layer 1) and the risk manager (the veto),
  5. submits an approved order through the executor (paper by default),
  6. settles resolved markets and updates the kill switch.

It is transport-agnostic: you inject the data sources and the executor, which
keeps it unit-testable without any network.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .brain.reasoner import build_brain
from .config import Config
from .data.binance import BinanceFeed
from .data.polymarket import PolymarketData
from .execution.executor import Executor, build_executor
from .execution.portfolio import Portfolio
from .models import Action, Market, Order, Side, Signal
from .risk.manager import RiskManager
from .strategy.latency_arb import LatencyArbStrategy

log = logging.getLogger("polybot.engine")


class TradingEngine:
    def __init__(
        self,
        config: Config,
        binance: Optional[BinanceFeed] = None,
        polymarket: Optional[PolymarketData] = None,
        executor: Optional[Executor] = None,
        brain=None,
    ):
        self.config = config
        self.binance = binance or BinanceFeed(config.binance_rest_url, config.binance_ws_url)
        self.polymarket = polymarket or PolymarketData(config.polymarket_clob_url, config.polymarket_gamma_url)
        self.executor = executor or build_executor(config)
        self.brain = brain or build_brain(config)
        self.strategy = LatencyArbStrategy(config.strategy)
        self.risk = RiskManager(config.risk)
        self.portfolio = Portfolio(cash_usd=config.risk.bankroll_usd)
        self.markets: dict[str, Market] = {}

    def track(self, market: Market) -> None:
        self.markets[market.market_id] = market

    # --- one decision cycle for one market ------------------------------

    def _apply_brain(self, market: Market, signal: Signal) -> Optional[Signal]:
        verdict = self.brain.assess(market, signal)
        if not verdict.approve:
            log.info("brain vetoed %s: %s", market.market_id, verdict.note)
            return None
        return Signal(
            market_id=signal.market_id,
            side=signal.side,
            fair_prob=signal.fair_prob,
            market_prob=signal.market_prob,
            edge=signal.edge,
            confidence=min(1.0, signal.confidence * verdict.confidence_multiplier),
            rationale=f"{signal.rationale} | brain: {verdict.note}",
            ts=signal.ts,
        )

    def evaluate_market(self, market: Market) -> Optional[Order]:
        """Run the full pipeline for one market; returns an Order if approved."""
        try:
            price = self.binance.get_price(market.underlying)
        except Exception as e:  # pragma: no cover - network
            log.warning("binance price fetch failed for %s: %s", market.underlying, e)
            return None

        up_quote = self.polymarket.best_quote(market.market_id, Side.UP, market.up_token_id)
        down_quote = self.polymarket.best_quote(market.market_id, Side.DOWN, market.down_token_id)
        if up_quote is None or down_quote is None:
            return None

        signal = self.strategy.evaluate(market, price, up_quote, down_quote)
        if signal is None:
            return None

        signal = self._apply_brain(market, signal)
        if signal is None:
            return None

        decision = self.risk.evaluate(
            signal,
            bankroll_usd=self.portfolio.equity_usd(),
            current_exposure_usd=self.portfolio.exposure_usd(),
        )
        if not decision.approved:
            log.info("risk vetoed %s: %s", market.market_id, decision.reason)
            return None

        quote = up_quote if signal.side is Side.UP else down_quote
        token_id = market.up_token_id if signal.side is Side.UP else market.down_token_id
        return Order(
            market_id=market.market_id,
            side=signal.side,
            action=Action.BUY,
            size_usd=decision.size_usd,
            limit_price=quote.best_ask,
            token_id=token_id,
        )

    def step(self) -> None:
        """One pass over all tracked markets."""
        if self.risk.kill_switch_tripped:
            log.error("KILL SWITCH TRIPPED (%s) — no trading", self.risk.kill_reason)
            return
        for market in list(self.markets.values()):
            order = self.evaluate_market(market)
            if order is None:
                continue
            fill = self.executor.submit(order)
            if fill is not None:
                self.portfolio.apply_fill(fill)
                log.info(
                    "filled %s %s $%.2f @ %.3f | equity=$%.2f",
                    order.market_id, order.side.value, fill.size_usd, fill.fill_price,
                    self.portfolio.equity_usd(),
                )
        self.risk.update_equity(self.portfolio.equity_usd())

    def run(self, max_cycles: Optional[int] = None, sleep: Optional[Callable[[float], None]] = None) -> None:
        """Run the loop. ``max_cycles=None`` runs forever; pass an int for tests."""
        sleep = sleep or time.sleep
        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            self.step()
            if self.risk.kill_switch_tripped:
                log.error("stopping: kill switch tripped")
                break
            cycle += 1
            if max_cycles is None or cycle < max_cycles:
                sleep(self.config.poll_interval_s)
