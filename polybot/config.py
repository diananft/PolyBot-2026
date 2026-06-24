"""Configuration and safety flags.

Every dangerous capability is *off* by default. Live trading requires an
explicit, deliberate opt-in. This mirrors the single quality the article
credits for the bot's survival: conservative defaults and a hard kill switch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RiskConfig:
    """Risk limits. The defaults are deliberately cautious."""

    bankroll_usd: float = 1_000.0
    # Fraction of full-Kelly to actually deploy. 1.0 == full Kelly (aggressive
    # and high-variance); we default to a quarter-Kelly, which is standard
    # practice for surviving estimation error in the edge.
    kelly_fraction: float = 0.25
    # Hard cap on any single position as a fraction of bankroll.
    max_position_fraction: float = 0.10
    # Minimum edge (fair_prob - market_prob) required to act at all.
    min_edge: float = 0.04
    # Minimum model confidence required to act.
    min_confidence: float = 0.55
    # Kill switch: stop all trading once cumulative drawdown from peak equity
    # exceeds this fraction.
    max_drawdown: float = 0.20
    # Stop after this many consecutive losing trades.
    max_consecutive_losses: int = 8
    # Max total fraction of bankroll deployed across all open positions.
    max_total_exposure_fraction: float = 0.50
    # Per-trade taker fee assumption (Polymarket fees vary; keep conservative).
    fee_rate: float = 0.02
    # Assumed slippage when crossing the spread, in probability units.
    slippage: float = 0.005


@dataclass
class StrategyConfig:
    # Annualised-ish volatility proxy used to translate a price move into a
    # change in resolution probability. Calibrated per underlying in practice.
    # Expressed as expected stdev of log-return over a 1-minute window.
    minute_vol: float = 0.004
    # Only act when at least this fraction of the contract window has elapsed
    # (early in the window the outcome is genuinely uncertain).
    min_fraction_elapsed: float = 0.30
    # Don't enter in the final seconds where we can't exit/settle cleanly.
    min_seconds_to_close: float = 20.0


@dataclass
class Config:
    # --- safety ---
    # When False (default) NO real orders are ever sent. Paper trading only.
    live_trading: bool = field(default_factory=lambda: _env_bool("POLYBOT_LIVE", False))
    # Extra belt-and-braces confirmation token required to go live.
    live_confirm: str = field(default_factory=lambda: os.getenv("POLYBOT_LIVE_CONFIRM", ""))

    # --- credentials (only needed for live or authenticated reads) ---
    polymarket_private_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    polymarket_api_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_KEY", ""))
    polymarket_api_secret: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_SECRET", ""))
    polymarket_api_passphrase: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_PASSPHRASE", ""))
    # Wallet type. 0 = EOA (MetaMask/private key holds the USDC directly).
    # 1 = email/Magic wallet, 2 = browser proxy wallet. For 1/2 you MUST also set
    # the funder to your Polymarket deposit/proxy address.
    polymarket_signature_type: int = field(default_factory=lambda: int(_env_float("POLYMARKET_SIGNATURE_TYPE", 0)))
    polymarket_funder: str = field(default_factory=lambda: os.getenv("POLYMARKET_FUNDER", ""))
    # Order time-in-force. FAK (fill-and-kill) suits a taker bot: fill what's on
    # the book now, cancel the rest — never leaves a resting order behind.
    order_type: str = field(default_factory=lambda: os.getenv("POLYBOT_ORDER_TYPE", "FAK"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # --- endpoints ---
    # Public market-data host: same /api/v3 endpoints as api.binance.com but not
    # geo-restricted (api.binance.com returns HTTP 451 in many regions). Override
    # via POLYBOT_BINANCE_REST if you have direct access.
    binance_ws_url: str = field(default_factory=lambda: os.getenv("POLYBOT_BINANCE_WS", "wss://data-stream.binance.vision/ws"))
    binance_rest_url: str = field(default_factory=lambda: os.getenv("POLYBOT_BINANCE_REST", "https://data-api.binance.vision"))
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"

    # --- use the AI brain? falls back to deterministic model if no key ---
    use_ai_brain: bool = field(default_factory=lambda: _env_bool("POLYBOT_AI_BRAIN", False))
    ai_model: str = field(default_factory=lambda: os.getenv("POLYBOT_AI_MODEL", "claude-opus-4-8"))

    # --- loop cadence ---
    poll_interval_s: float = field(default_factory=lambda: _env_float("POLYBOT_POLL_INTERVAL", 2.0))

    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)

    def can_trade_live(self) -> tuple[bool, str]:
        """Gate that decides whether live order submission is permitted.

        Returns (allowed, reason). Multiple independent conditions must all be
        satisfied — a single mis-set env var cannot accidentally arm live mode.
        """
        if not self.live_trading:
            return False, "live_trading disabled (paper mode)"
        if self.live_confirm != "I_UNDERSTAND_THE_RISK":
            return False, "POLYBOT_LIVE_CONFIRM not set to the required token"
        if not self.polymarket_private_key:
            return False, "no POLYMARKET_PRIVATE_KEY configured"
        return True, "ok"

    def to_dict(self) -> dict:
        d = asdict(self)
        # Never echo secrets.
        for k in list(d):
            if "key" in k or "secret" in k or "passphrase" in k or "confirm" in k:
                d[k] = "***" if d[k] else ""
        return d


def load_config() -> Config:
    return Config()
