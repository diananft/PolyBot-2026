"""Market discovery: turn live Polymarket Gamma data into Market objects.

The Gamma `/markets` response encodes the two outcome token ids as a
JSON-*string* array aligned with `outcomes` (typically ["Yes", "No"]). We map
Yes -> UP and No -> DOWN, parse the ISO-8601 window, infer the underlying from
the question text, and seed the reference open price from Binance.

The keyword and timing filters that select *short-duration crypto up/down*
markets are configurable, because Polymarket reorganises these recurring series
periodically. Parsing is pure and unit-tested against the real schema; only the
seeding of open prices and the HTTP fetch touch the network.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .data.binance import BinanceFeed
from .data.polymarket import PolymarketData
from .models import Market

log = logging.getLogger("polybot.discovery")

# question keyword -> Binance symbol (only assets with a liquid Binance USDT pair)
_UNDERLYING_MAP = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "bnb": "BNBUSDT",
    "dogecoin": "DOGEUSDT",
    "doge": "DOGEUSDT",
    "xrp": "XRPUSDT",
}

# Phrasing used by the short-duration up/down series.
_UPDOWN_KEYWORDS = ("up or down", "higher", "above", "go up", "price be")

# Title window, e.g. "...10:30AM-10:45AM ET".
_TIME_RANGE = re.compile(
    r"(\d{1,2}):(\d{2})\s*([AP]M)\s*-\s*(\d{1,2}):(\d{2})\s*([AP]M)", re.IGNORECASE
)


def _to_minutes(h: int, m: int, ap: str) -> int:
    h = h % 12
    if ap.upper() == "PM":
        h += 12
    return h * 60 + m


def parse_window_seconds(title: str) -> Optional[float]:
    """Duration of the trading window parsed from the event title.

    The market's `startDate` field is the deploy time, not the window open, so
    we derive the window length from the title and anchor it to the close.
    """
    match = _TIME_RANGE.search(title or "")
    if not match:
        return None
    h1, m1, ap1, h2, m2, ap2 = match.groups()
    dur = _to_minutes(int(h1), int(m1), ap1) - 0  # start
    dur = _to_minutes(int(h2), int(m2), ap2) - _to_minutes(int(h1), int(m1), ap1)
    if dur < 0:
        dur += 12 * 60  # AM/PM wrap guard
    return dur * 60 if dur > 0 else None


def parse_iso8601(s: str) -> Optional[float]:
    """Parse an ISO-8601 timestamp to unix seconds. Returns None on failure."""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() \
            if "+" not in s else datetime.fromisoformat(s).timestamp()
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except ValueError:
            return None


def infer_underlying(question: str) -> Optional[str]:
    q = question.lower()
    for kw, sym in _UNDERLYING_MAP.items():
        if kw in q:
            return sym
    return None


def _loads_list(raw) -> list:
    """Gamma encodes some array fields as JSON strings; tolerate both."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except json.JSONDecodeError:
            return []
    return []


def build_market(
    raw: dict,
    open_price: float,
    underlying: Optional[str] = None,
    open_ts: Optional[float] = None,
    close_ts: Optional[float] = None,
) -> Optional[Market]:
    """Convert one Gamma market dict into a Market, or None if unusable.

    ``open_price`` is the reference underlying price the up/down outcome is
    measured against. ``open_ts``/``close_ts`` override the dates parsed from
    the raw dict (used for events, whose window comes from the title, not the
    deploy-time startDate field).
    """
    question = raw.get("question") or raw.get("title") or ""
    underlying = underlying or infer_underlying(question)
    if not underlying:
        return None

    token_ids = _loads_list(raw.get("clobTokenIds"))
    outcomes = _loads_list(raw.get("outcomes"))
    if len(token_ids) < 2 or len(outcomes) < 2:
        return None

    # Map Yes/Up->UP, No/Down->DOWN by outcome label; fall back to order.
    up_token = down_token = ""
    for label, tid in zip(outcomes, token_ids):
        l = str(label).strip().lower()
        if l in ("yes", "up", "higher"):
            up_token = str(tid)
        elif l in ("no", "down", "lower"):
            down_token = str(tid)
    if not up_token or not down_token:
        up_token, down_token = str(token_ids[0]), str(token_ids[1])

    if open_ts is None:
        open_ts = parse_iso8601(raw.get("startDate") or "")
    if close_ts is None:
        close_ts = parse_iso8601(raw.get("endDate") or "")
    if open_ts is None or close_ts is None or close_ts <= open_ts:
        return None

    return Market(
        market_id=str(raw.get("id") or raw.get("conditionId") or question),
        question=question,
        underlying=underlying,
        open_ts=open_ts,
        close_ts=close_ts,
        open_price=open_price,
        up_token_id=up_token,
        down_token_id=down_token,
    )


def is_short_duration_crypto(title: str, window_s: Optional[float], max_window_s: float) -> bool:
    """A crypto up/down market whose parsed window is short."""
    t = (title or "").lower()
    if infer_underlying(t) is None:
        return False
    if not any(k in t for k in _UPDOWN_KEYWORDS):
        return False
    return window_s is not None and 0 < window_s <= max_window_s


def markets_from_event(event: dict, max_window_s: float) -> list[tuple[dict, str, float, float]]:
    """Extract tradeable (raw_market, underlying, open_ts, close_ts) tuples.

    Pure (no network): resolves the window from the event/market title and
    anchors open_ts to the close. Skips non-crypto / non-short events.
    """
    title = event.get("title") or ""
    window_s = parse_window_seconds(title)
    underlying = infer_underlying(title)
    out: list[tuple[dict, str, float, float]] = []
    for raw in event.get("markets", []) or []:
        m_title = raw.get("question") or title
        m_window = parse_window_seconds(m_title) or window_s
        m_under = infer_underlying(m_title) or underlying
        if m_under is None or not is_short_duration_crypto(m_title, m_window, max_window_s):
            continue
        close_ts = parse_iso8601(raw.get("endDate") or "")
        if close_ts is None or m_window is None:
            continue
        open_ts = close_ts - m_window
        out.append((raw, m_under, open_ts, close_ts))
    return out


def discover_markets(
    polymarket: PolymarketData,
    binance: BinanceFeed,
    limit: int = 100,
    max_window_s: float = 3600.0,
    min_seconds_to_close: float = 30.0,
) -> list[Market]:
    """Fetch live events and return tradeable short-duration crypto Markets.

    Networked. Each market's reference open price is seeded from Binance at the
    window open. Markets already past (or about to pass) close are skipped.
    """
    import time

    now = time.time()
    # Query events closing between now and now+max_window: this is what surfaces
    # currently-active short windows instead of the many deployed ~24h early.
    events = polymarket.list_events(
        limit=limit, end_date_min=now, end_date_max=now + max_window_s,
    )
    out: list[Market] = []
    for event in events:
        for raw, underlying, open_ts, close_ts in markets_from_event(event, max_window_s):
            # Only trade windows that are actually open right now. Polymarket
            # deploys these markets ~24h early; future windows have no edge yet
            # and a meaningless open price.
            if not (open_ts <= now < close_ts):
                continue
            if close_ts - now < min_seconds_to_close:
                continue
            try:
                open_price = binance.get_price_at(underlying, open_ts).price
            except Exception as e:  # pragma: no cover - network
                log.warning("open-price seed failed for %s: %s", raw.get("id"), e)
                continue
            market = build_market(
                raw, open_price=open_price, underlying=underlying,
                open_ts=open_ts, close_ts=close_ts,
            )
            if market is not None:
                out.append(market)
    log.info("discovered %d short-duration crypto markets", len(out))
    return out
