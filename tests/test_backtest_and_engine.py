import time

from polybot.config import Config
from polybot.backtest.engine import Backtester
from polybot.demo import build_demo_scenarios, run_demo
from polybot.engine import TradingEngine
from polybot.execution.executor import PaperExecutor
from polybot.models import Action, Market, MarketQuote, PricePoint, Side


def test_backtest_runs_and_is_deterministic():
    r1 = run_demo(n=50, seed=3)
    r2 = run_demo(n=50, seed=3)
    assert r1.final_equity == r2.final_equity
    assert r1.n_trades == r2.n_trades


def test_backtest_produces_trades_and_equity_curve():
    res = run_demo(n=100, seed=1)
    assert res.n_trades > 0
    assert len(res.equity_curve) == 101  # initial + one per market
    assert res.win_rate >= 0.0


def test_demo_scenarios_have_consistent_outcomes():
    for sc in build_demo_scenarios(n=20):
        expected = Side.UP if sc.close_price > sc.market.open_price else Side.DOWN
        assert sc.won_side is expected


class _StubBinance:
    def __init__(self, price):
        self._price = price

    def get_price(self, symbol):
        return PricePoint(symbol, self._price)


class _StubPoly:
    def __init__(self, up_ask, down_ask):
        self._up, self._down = up_ask, down_ask

    def best_quote(self, market_id, side, token_id):
        ask = self._up if side is Side.UP else self._down
        return MarketQuote(market_id, side, ask - 0.01, ask)


def test_engine_full_pipeline_paper_trade():
    now = time.time()
    cfg = Config()
    engine = TradingEngine(
        cfg,
        binance=_StubBinance(100.6),               # underlying moved up
        polymarket=_StubPoly(up_ask=0.52, down_ask=0.50),  # stale quote
        executor=PaperExecutor(cfg.risk.slippage, cfg.risk.fee_rate),
    )
    m = Market("m", "BTC up?", "BTCUSDT", open_ts=now - 540, close_ts=now + 360,
               open_price=100.0, up_token_id="u", down_token_id="d")
    engine.track(m)
    engine.step()
    # Should have opened a long UP position.
    assert ("m", Side.UP) in engine.portfolio.positions


def test_engine_respects_kill_switch():
    cfg = Config()
    engine = TradingEngine(
        cfg,
        binance=_StubBinance(100.6),
        polymarket=_StubPoly(0.52, 0.50),
        executor=PaperExecutor(0.0, 0.0),
    )
    engine.risk._trip("test")
    now = time.time()
    engine.track(Market("m", "q", "BTCUSDT", now - 540, now + 360, 100.0, "u", "d"))
    engine.step()
    assert ("m", Side.UP) not in engine.portfolio.positions
