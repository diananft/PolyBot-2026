"""Layer 3 — Polymarket market data (the slow feed we arbitrage).

Read-only access to the public Gamma (metadata) and CLOB (order book) APIs.
Stdlib HTTP only; no keys required for reads. Order *placement* lives in the
execution layer, not here.
"""

from __future__ import annotations

import datetime
import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

from ..models import MarketQuote, Side

log = logging.getLogger("polybot.polymarket")


def _iso_utc(ts: float) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    def _get(self, url: str, retries: int = 3) -> dict | list:
        req = urllib.request.Request(url, headers={"User-Agent": "polybot/1.0"})
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # transient read/connection errors
                last = e
                log.debug("GET %s failed (attempt %d): %s", url, attempt + 1, e)
        raise last  # type: ignore[misc]

    def list_markets(self, limit: int = 50, active: bool = True) -> list[dict]:
        """Fetch markets from the Gamma API."""
        params = urllib.parse.urlencode({"limit": limit, "active": str(active).lower(), "closed": "false"})
        url = f"{self.gamma_url}/markets?{params}"
        data = self._get(url)
        return data if isinstance(data, list) else data.get("data", [])  # type: ignore[union-attr]

    def list_events(
        self,
        limit: int = 100,
        order: str = "endDate",
        ascending: bool = True,
        end_date_min: Optional[float] = None,
        end_date_max: Optional[float] = None,
    ) -> list[dict]:
        """Fetch events from the Gamma API. Short-duration crypto up/down
        series (5/15-minute BTC, ETH, SOL... markets) are exposed here, each
        event wrapping one or more nested markets.

        ``end_date_min``/``end_date_max`` (unix seconds) restrict to events
        closing in a window — the reliable way to surface *currently active*
        markets rather than the thousands deployed ~24h early for future
        windows."""
        q = {
            "closed": "false", "active": "true", "limit": limit,
            "order": order, "ascending": str(ascending).lower(),
        }
        if end_date_min is not None:
            q["end_date_min"] = _iso_utc(end_date_min)
        if end_date_max is not None:
            q["end_date_max"] = _iso_utc(end_date_max)
        url = f"{self.gamma_url}/events?{urllib.parse.urlencode(q)}"
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
