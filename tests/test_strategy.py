import time

from polybot.config import StrategyConfig
from polybot.models import Market, MarketQuote, PricePoint, Side
from polybot.strategy.latency_arb import LatencyArbStrategy


def make_market(open_price=100.0, window=900.0, now=None):
    now = now or time.time()
    return Market(
        market_id="m", question="BTC up?", underlying="BTCUSDT",
        open_ts=now - window * 0.6, close_ts=now + window * 0.4,
        open_price=open_price, up_token_id="u", down_token_id="d",
    )


def quotes(up_ask, down_ask, spread=0.01):
    up = MarketQuote("m", Side.UP, up_ask - spread, up_ask)
    down = MarketQuote("m", Side.DOWN, down_ask - spread, down_ask)
    return up, down


def test_emits_up_signal_when_price_rose_but_quote_stale():
    now = time.time()
    m = make_market(open_price=100.0, now=now)
    price = PricePoint("BTCUSDT", 100.6)  # moved up
    up, down = quotes(up_ask=0.52, down_ask=0.50)  # stale ~50/50
    sig = LatencyArbStrategy().evaluate(m, price, up, down, now=now)
    assert sig is not None
    assert sig.side is Side.UP
    assert sig.edge > 0


def test_no_signal_when_market_already_efficient():
    now = time.time()
    m = make_market(open_price=100.0, now=now)
    price = PricePoint("BTCUSDT", 100.6)
    # Fair up here is ~0.73. Quote both sides at/above fair -> no positive edge
    # to capture on either side.
    up, down = quotes(up_ask=0.76, down_ask=0.30)
    sig = LatencyArbStrategy().evaluate(m, price, up, down, now=now)
    assert sig is None


def test_filters_when_too_early():
    now = time.time()
    cfg = StrategyConfig(min_fraction_elapsed=0.30)
    # Window just opened (1% elapsed).
    m = Market("m", "q", "BTCUSDT", open_ts=now - 9, close_ts=now + 891,
               open_price=100.0, up_token_id="u", down_token_id="d")
    price = PricePoint("BTCUSDT", 100.6)
    up, down = quotes(0.52, 0.50)
    assert LatencyArbStrategy(cfg).evaluate(m, price, up, down, now=now) is None


def test_filters_when_too_late():
    now = time.time()
    cfg = StrategyConfig(min_seconds_to_close=20)
    m = Market("m", "q", "BTCUSDT", open_ts=now - 895, close_ts=now + 5,
               open_price=100.0, up_token_id="u", down_token_id="d")
    price = PricePoint("BTCUSDT", 100.6)
    up, down = quotes(0.52, 0.50)
    assert LatencyArbStrategy(cfg).evaluate(m, price, up, down, now=now) is None
