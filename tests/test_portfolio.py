from polybot.execution.portfolio import Portfolio
from polybot.models import Action, Fill, Order, Side


def buy_fill(market_id, side, size_usd, price, fee=0.0):
    order = Order(market_id, side, Action.BUY, size_usd, price)
    return Fill(order=order, fill_price=price, size_usd=size_usd, fee_usd=fee)


def test_apply_fill_spends_cash_and_holds_shares():
    p = Portfolio(cash_usd=1000)
    p.apply_fill(buy_fill("m", Side.UP, 100, 0.5, fee=2))
    pos = p.positions[("m", Side.UP)]
    assert pos.shares == 200          # 100 / 0.5
    assert pos.cost_usd == 100
    assert p.cash_usd == 1000 - 100 - 2
    assert p.fees_paid_usd == 2


def test_settlement_winner_pays_one_per_share():
    p = Portfolio(cash_usd=1000)
    p.apply_fill(buy_fill("m", Side.UP, 100, 0.5))
    pnl = p.settle("m", won_side=Side.UP)
    # 200 shares pay $1 each = $200, cost was $100 -> +100 PnL.
    assert abs(pnl - 100) < 1e-9
    assert ("m", Side.UP) not in p.positions
    assert abs(p.cash_usd - (900 + 200)) < 1e-9


def test_settlement_loser_pays_zero():
    p = Portfolio(cash_usd=1000)
    p.apply_fill(buy_fill("m", Side.UP, 100, 0.5))
    pnl = p.settle("m", won_side=Side.DOWN)
    assert abs(pnl - (-100)) < 1e-9


def test_exposure_tracks_open_cost():
    p = Portfolio(cash_usd=1000)
    p.apply_fill(buy_fill("a", Side.UP, 100, 0.5))
    p.apply_fill(buy_fill("b", Side.DOWN, 50, 0.4))
    assert abs(p.exposure_usd() - 150) < 1e-9


def test_equity_marks_to_market():
    p = Portfolio(cash_usd=900)  # after spending 100
    p.apply_fill(buy_fill("m", Side.UP, 100, 0.5))  # cash now 800, 200 shares
    # Mark at 0.6 -> 200 * 0.6 = 120 value.
    eq = p.equity_usd({("m", Side.UP): 0.6})
    assert abs(eq - (800 + 120)) < 1e-9


def test_realised_pnl_accumulates():
    p = Portfolio(cash_usd=1000)
    p.apply_fill(buy_fill("a", Side.UP, 100, 0.5))
    p.apply_fill(buy_fill("b", Side.UP, 100, 0.5))
    p.settle("a", Side.UP)   # +100
    p.settle("b", Side.DOWN)  # -100
    assert abs(p.realised_pnl - 0.0) < 1e-9
