"""Layer 3 — the fast feed. Binance price source.

The latency edge is born here: Binance reflects the real move seconds before
Polymarket re-prices. We provide a simple REST poller (stdlib only, no keys)
and an optional WebSocket streamer (requires the ``websockets`` package) for
sub-second updates.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import AsyncIterator, Iterable

from ..models import PricePoint

log = logging.getLogger("polybot.binance")


class BinanceFeed:
    def __init__(self, rest_url: str = "https://api.binance.com", ws_url: str = "wss://stream.binance.com:9443/ws", timeout: float = 5.0):
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self.timeout = timeout

    def get_price(self, symbol: str) -> PricePoint:
        """One-shot REST price fetch. ``symbol`` like 'BTCUSDT'."""
        url = f"{self.rest_url}/api/v3/ticker/price?symbol={symbol.upper()}"
        with urllib.request.urlopen(url, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        return PricePoint(symbol=symbol.upper(), price=float(data["price"]))

    def get_prices(self, symbols: Iterable[str]) -> dict[str, PricePoint]:
        return {s: self.get_price(s) for s in symbols}

    async def stream(self, symbol: str) -> AsyncIterator[PricePoint]:
        """Yield live trade prices from the WebSocket feed.

        Requires ``pip install websockets``. Falls back with a clear error if
        the dependency is missing.
        """
        try:
            import websockets  # type: ignore
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError("websockets package required for streaming: pip install websockets") from e

        stream_name = f"{symbol.lower()}@trade"
        url = f"{self.ws_url}/{stream_name}"
        async with websockets.connect(url) as ws:  # pragma: no cover - network
            async for raw in ws:
                msg = json.loads(raw)
                if "p" in msg:
                    yield PricePoint(symbol=symbol.upper(), price=float(msg["p"]))
