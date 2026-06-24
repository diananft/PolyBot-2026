"""Layer 3 — Polymarket market data (the slow feed we arbitrage).

Read-only access to the public Gamma (metadata) and CLOB (order book) APIs.
Stdlib HTTP only; no keys required for reads. Order *placement* lives in the
execution layer, not here.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

from ..models import MarketQuote, Side

log = logging.getLogger("polybot.polymarket")


class PolymarketData:
    def __init__(
        self,
        clob_url: str = "https://clob.polymarket.com",
        gamma_url: str = "https://gamma-api.polymarket.com",
        timeout: float = 5.0,
    ):
        self.clob_url = clob_url.rstrip("/")
        self.gamma_url = gamma_url.rstrip("/")
        self.timeout = timeout

    def _get(self, url: str) -> dict | list:
        req = urllib.request.Request(url, headers={"User-Agent": "polybot/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def list_markets(self, limit: int = 50, active: bool = True) -> list[dict]:
        """Fetch markets from the Gamma API."""
        params = urllib.parse.urlencode({"limit": limit, "active": str(active).lower(), "closed": "false"})
        url = f"{self.gamma_url}/markets?{params}"
        data = self._get(url)
        return data if isinstance(data, list) else data.get("data", [])  # type: ignore[union-attr]

    def get_order_book(self, token_id: str) -> dict:
        """Fetch the CLOB order book for a single outcome token."""
        url = f"{self.clob_url}/book?token_id={urllib.parse.quote(token_id)}"
        return self._get(url)  # type: ignore[return-value]

    def best_quote(self, market_id: str, side: Side, token_id: str) -> Optional[MarketQuote]:
        """Build a MarketQuote from the live order book for one token."""
        try:
            book = self.get_order_book(token_id)
        except Exception as e:  # pragma: no cover - network
            log.warning("order book fetch failed for %s: %s", token_id, e)
            return None
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return None
        # CLOB returns price strings; best bid is the highest, best ask the lowest.
        best_bid = max(float(b["price"]) for b in bids)
        best_ask = min(float(a["price"]) for a in asks)
        return MarketQuote(
            market_id=market_id,
            side=side,
            best_bid=best_bid,
            best_ask=best_ask,
        )
