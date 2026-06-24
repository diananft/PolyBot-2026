import time

from polybot.config import Config
from polybot.live_runner import LiveRunner
from polybot.models import MarketQuote, PricePoint, Side


class _StubBinance:
    """Underlying opened at 100, now trading 100.6, closes at 101 (UP wins)."""

    def get_price(self, symbol):
        return PricePoint(symbol, 100.6)

    def get_price_at(self, symbol, ts):
        # The open seed asks for an old ts (~9 min ago) -> 100. The resolve path
        # asks for the recent close ts -> 101 (UP wins).
        return PricePoint(symbol, 101.0 if ts > time.time() - 120 else 100.0)


class _StubPoly:
    def __init__(self, events):
        self._events = events

    def list_events(self, limit=100, order="endDate", ascending=True,
                    end_date_min=None, end_date_max=None):
        return self._events

    def best_quote(self, market_id, side, token_id):
        ask = 0.52 if side is Side.UP else 0.50  # stale ~50/50
        return MarketQuote(market_id, side, ask - 0.01, ask)


def _raw_event(now):
    # 15-minute window ending ~6 min from now (open ~9 min ago).
    close_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 360))
    return {
        "title": "Bitcoin Up or Down - 10:30AM-10:45AM ET",
        "markets": [{
            "id": "live-1",
            "question": "Bitcoin Up or Down - 10:30AM-10:45AM ET",
            "clobTokenIds": '["t-up", "t-down"]',
            "outcomes": '["Up", "Down"]',
            "startDate": "2026-06-24T00:00:00Z",  # deploy time (ignored)
            "endDate": close_iso,
        }],
    }


def _future_event(now):
    # Window is entirely in the future (deployed ~24h early) -> must be skipped.
    close_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 24 * 3600))
    return {
        "title": "Bitcoin Up or Down - 10:30AM-10:45AM ET",
        "markets": [{
            "id": "future-1",
            "question": "Bitcoin Up or Down - 10:30AM-10:45AM ET",
            "clobTokenIds": '["t-up", "t-down"]',
            "outcomes": '["Up", "Down"]',
            "startDate": "2026-06-24T00:00:00Z",
            "endDate": close_iso,
        }],
    }


def test_runner_discovers_and_tracks():
    now = time.time()
    cfg = Config()
    runner = LiveRunner(cfg, binance=_StubBinance(), polymarket=_StubPoly([_raw_event(now)]))
    added = runner.discover_and_track()
    assert added == 1
    assert "live-1" in runner.engine.markets


def test_runner_skips_future_windows():
    now = time.time()
    cfg = Config()
    runner = LiveRunner(cfg, binance=_StubBinance(), polymarket=_StubPoly([_future_event(now)]))
    assert runner.discover_and_track() == 0
    assert len(runner.engine.markets) == 0


def test_runner_paper_trades_and_resolves():
    now = time.time()
    cfg = Config()
    runner = LiveRunner(cfg, binance=_StubBinance(), polymarket=_StubPoly([_raw_event(now)]))
    # One full cycle: discover, trade, (not yet expired) — bounded for the test.
    runner.run(max_cycles=1, sleep=lambda s: None)
    assert runner.engine.holds_position("live-1")

    # Force the market past close and resolve it.
    m = runner.engine.markets["live-1"]
    object.__setattr__(m, "close_ts", now - 1)  # frozen dataclass
    resolved = runner.resolve_expired(now=now)
    assert resolved == 1
    assert "live-1" not in runner.engine.markets
    # UP won (close 101 > open 100) and we bought UP cheap -> realised profit.
    assert runner.engine.portfolio.realised_pnl > 0
