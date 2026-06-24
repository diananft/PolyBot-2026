"""Risk manager: the veto layer.

The article's whole thesis is that survival comes from risk management, not
forecasting. This class is the single chokepoint every prospective trade must
pass through. It owns the kill switch.

Responsibilities:
  * translate a Signal into a risk-approved USD size (or reject it),
  * enforce per-trade, per-portfolio and drawdown limits,
  * trip a hard kill switch on excessive drawdown or a losing streak.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import RiskConfig
from ..models import Signal
from ..strategy.kelly import position_size_usd


@dataclass
class RiskDecision:
    approved: bool
    size_usd: float
    reason: str


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.peak_equity = config.bankroll_usd
        self.consecutive_losses = 0
        self.kill_switch_tripped = False
        self.kill_reason = ""

    # --- equity / kill-switch bookkeeping -------------------------------

    def update_equity(self, equity_usd: float) -> None:
        """Feed the latest mark-to-market equity; trips the kill switch if the
        drawdown from the peak exceeds the configured maximum."""
        self.peak_equity = max(self.peak_equity, equity_usd)
        if self.peak_equity <= 0:
            return
        drawdown = (self.peak_equity - equity_usd) / self.peak_equity
        if drawdown >= self.config.max_drawdown:
            self._trip(f"max drawdown {drawdown:.1%} >= {self.config.max_drawdown:.1%}")

    def record_trade_result(self, pnl_usd: float) -> None:
        """Track consecutive losses for the streak-based kill switch."""
        if pnl_usd < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self._trip(
                    f"{self.consecutive_losses} consecutive losses "
                    f">= {self.config.max_consecutive_losses}"
                )
        else:
            self.consecutive_losses = 0

    def _trip(self, reason: str) -> None:
        if not self.kill_switch_tripped:
            self.kill_switch_tripped = True
            self.kill_reason = reason

    def reset_kill_switch(self) -> None:
        self.kill_switch_tripped = False
        self.kill_reason = ""
        self.consecutive_losses = 0

    # --- the veto -------------------------------------------------------

    def evaluate(
        self,
        signal: Signal,
        bankroll_usd: float,
        current_exposure_usd: float,
    ) -> RiskDecision:
        if self.kill_switch_tripped:
            return RiskDecision(False, 0.0, f"kill switch tripped: {self.kill_reason}")

        if signal.edge < self.config.min_edge:
            return RiskDecision(
                False, 0.0,
                f"edge {signal.edge:.3f} < min {self.config.min_edge:.3f}",
            )
        if signal.confidence < self.config.min_confidence:
            return RiskDecision(
                False, 0.0,
                f"confidence {signal.confidence:.2f} < min {self.config.min_confidence:.2f}",
            )

        size = position_size_usd(
            win_prob=signal.fair_prob,
            price=signal.market_prob,
            bankroll_usd=bankroll_usd,
            kelly_fraction_used=self.config.kelly_fraction,
            max_position_fraction=self.config.max_position_fraction,
        )
        if size <= 0:
            return RiskDecision(False, 0.0, "kelly size non-positive")

        # Cap by remaining portfolio exposure budget.
        max_total = self.config.max_total_exposure_fraction * bankroll_usd
        remaining = max_total - current_exposure_usd
        if remaining <= 0:
            return RiskDecision(
                False, 0.0,
                f"portfolio exposure {current_exposure_usd:.0f} at cap {max_total:.0f}",
            )
        size = min(size, remaining)

        return RiskDecision(True, size, "approved")
