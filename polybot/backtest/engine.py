"""Layer 5 — backtest & simulation.

Replays a sequence of (market, underlying-price-path) scenarios through the
exact same strategy → brain → risk → paper-execution pipeline used live, then
settles each market against its realised outcome. This is the "earn your way to
production" gate the article says most retail bots skip.

A scenario is deliberately simple and self-contained so backtests need no
network: you supply the market, a list of (timestamp, price) ticks for the
underlying, synthetic quotes, and the true closing price.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..brain.reasoner import DeterministicBrain
from ..config import Config
from ..execution.executor import PaperExecutor
from ..execution.portfolio import Portfolio
from ..models import Action, Market, MarketQuote, Order, PricePoint, Side
from ..risk.manager import RiskManager
from ..strategy.latency_arb import LatencyArbStrategy


@dataclass
class Scenario:
    market: Market
    ticks: list[PricePoint]                       # underlying price path
    quotes: dict[Side, MarketQuote]               # static quotes (best bid/ask)
    close_price: float                            # realised underlying at close

    @property
    def won_side(self) -> Side:
        return Side.UP if self.close_price > self.market.open_price else Side.DOWN


@dataclass
class BacktestResult:
    final_equity: float
    realised_pnl: float
    n_trades: int
    n_wins: int
    fees_paid: float
    max_drawdown: float
    kill_switch_tripped: bool
    equity_curve: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_trades if self.n_trades else 0.0

    @property
    def roi(self) -> float:
        start = self.equity_curve[0] if self.equity_curve else 0.0
        return (self.final_equity - start) / start if start else 0.0


class Backtester:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.strategy = LatencyArbStrategy(self.config.strategy)
        self.brain = DeterministicBrain()

    def run(self, scenarios: list[Scenario]) -> BacktestResult:
        cfg = self.config
        portfolio = Portfolio(cash_usd=cfg.risk.bankroll_usd)
        risk = RiskManager(cfg.risk)
        executor = PaperExecutor(cfg.risk.slippage, cfg.risk.fee_rate)

        equity_curve = [portfolio.equity_usd()]
        peak = equity_curve[0]
        max_dd = 0.0

        for scenario in scenarios:
            market = scenario.market
            # Walk the price path; act on the first tick that yields an approved
            # trade for this market (one position per market in the backtest).
            entered = False
            for tick in scenario.ticks:
                if entered:
                    break
                signal = self.strategy.evaluate(
                    market,
                    tick,
                    scenario.quotes[Side.UP],
                    scenario.quotes[Side.DOWN],
                    now=tick.ts,
                )
                if signal is None:
                    continue
                verdict = self.brain.assess(market, signal, now=tick.ts)
                if not verdict.approve:
                    continue
                adj = signal.__class__(
                    market_id=signal.market_id,
                    side=signal.side,
                    fair_prob=signal.fair_prob,
                    market_prob=signal.market_prob,
                    edge=signal.edge,
                    confidence=min(1.0, signal.confidence * verdict.confidence_multiplier),
                    rationale=signal.rationale,
                    ts=signal.ts,
                )
                decision = risk.evaluate(
                    adj,
                    bankroll_usd=portfolio.equity_usd(),
                    current_exposure_usd=portfolio.exposure_usd(),
                )
                if not decision.approved:
                    continue
                quote = scenario.quotes[signal.side]
                order = Order(
                    market_id=market.market_id,
                    side=signal.side,
                    action=Action.BUY,
                    size_usd=decision.size_usd,
                    limit_price=quote.best_ask,
                )
                fill = executor.submit(order)
                if fill is not None:
                    portfolio.apply_fill(fill)
                    entered = True

            # Settle the market against the realised outcome.
            pnl = portfolio.settle(market.market_id, scenario.won_side)
            if entered:
                risk.record_trade_result(pnl)

            equity = portfolio.equity_usd()
            risk.update_equity(equity)
            equity_curve.append(equity)
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)

        # Each settled side we held produces one ClosedTrade record.
        n_trades = len(portfolio.closed)
        n_wins = sum(1 for t in portfolio.closed if t.pnl_usd > 0)

        return BacktestResult(
            final_equity=portfolio.equity_usd(),
            realised_pnl=portfolio.realised_pnl,
            n_trades=n_trades,
            n_wins=n_wins,
            fees_paid=portfolio.fees_paid_usd,
            max_drawdown=max_dd,
            kill_switch_tripped=risk.kill_switch_tripped,
            equity_curve=equity_curve,
        )
