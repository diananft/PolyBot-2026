"""Live runner: discovery + execution loop for real Polymarket markets.

Wires market discovery into the TradingEngine and drives the full lifecycle:
periodically discover fresh short-duration crypto markets, trade approved
signals (paper by default, live only when the three gates are armed), and
resolve markets once their window closes.

Resolution: these markets resolve on whether the underlying closed above its
open. We recover the close price from Binance and settle internally so the
risk manager's PnL, drawdown and loss-streak kill switch stay accurate. In
*live* mode the on-chain settlement is the source of truth for your actual
balance; this internal settlement keeps the bot's own risk state correct.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .config import Config
from .data.binance import BinanceFeed
from .data.polymarket import PolymarketData
from .discovery import discover_markets
from .engine import TradingEngine
from .models import Side

log = logging.getLogger("polybot.live_runner")


class LiveRunner:
    def __init__(
        self,
        config: Config,
        engine: Optional[TradingEngine] = None,
        binance: Optional[BinanceFeed] = None,
        polymarket: Optional[PolymarketData] = None,
        discovery_interval_s: float = 60.0,
        max_window_s: float = 3600.0,
    ):
        self.config = config
        self.binance = binance or BinanceFeed(config.binance_rest_url, config.binance_ws_url)
        self.polymarket = polymarket or PolymarketData(config.polymarket_clob_url, config.polymarket_gamma_url)
        self.engine = engine or TradingEngine(config, binance=self.binance, polymarket=self.polymarket)
        self.discovery_interval_s = discovery_interval_s
        self.max_window_s = max_window_s
        self._last_discovery = 0.0

    def discover_and_track(self) -> int:
        markets = discover_markets(
            self.polymarket,
            self.binance,
            max_window_s=self.max_window_s,
            min_seconds_to_close=self.config.strategy.min_seconds_to_close,
        )
        added = 0
        for m in markets:
            if m.market_id not in self.engine.markets:
                self.engine.track(m)
                added += 1
        self._last_discovery = time.time()
        log.info("tracking %d markets (+%d new)", len(self.engine.markets), added)
        return added

    def resolve_expired(self, now: Optional[float] = None) -> int:
        now = now if now is not None else time.time()
        resolved = 0
        for market in list(self.engine.markets.values()):
            if market.close_ts > now:
                continue
            try:
                close_price = self.binance.get_price_at(market.underlying, market.close_ts).price
            except Exception as e:  # pragma: no cover - network
                log.warning("close-price fetch failed for %s: %s", market.market_id, e)
                continue
            won = Side.UP if close_price > market.open_price else Side.DOWN
            self.engine.resolve_market(market.market_id, won)
            resolved += 1
        return resolved

    def run(self, max_cycles: Optional[int] = None, sleep: Optional[Callable[[float], None]] = None) -> None:
        """Drive the live loop. ``max_cycles=None`` runs forever."""
        sleep = sleep or time.sleep
        allowed, reason = self.config.can_trade_live()
        log.warning("LIVE TRADING" if allowed else "PAPER TRADING (%s)", reason)

        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            now = time.time()
            if now - self._last_discovery >= self.discovery_interval_s or not self.engine.markets:
                try:
                    self.discover_and_track()
                except Exception as e:  # pragma: no cover - network
                    log.warning("discovery failed: %s", e)

            self.engine.step()
            self.resolve_expired()

            if self.engine.risk.kill_switch_tripped:
                log.error("stopping: kill switch tripped (%s)", self.engine.risk.kill_reason)
                break

            cycle += 1
            if max_cycles is None or cycle < max_cycles:
                sleep(self.config.poll_interval_s)
