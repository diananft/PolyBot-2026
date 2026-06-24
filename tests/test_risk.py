from polybot.config import RiskConfig
from polybot.models import Side, Signal
from polybot.risk.manager import RiskManager


def make_signal(edge=0.10, confidence=0.8, fair=0.6, price=0.5):
    return Signal(
        market_id="m", side=Side.UP, fair_prob=fair, market_prob=price,
        edge=edge, confidence=confidence,
    )


def test_approves_good_signal():
    rm = RiskManager(RiskConfig(bankroll_usd=1000))
    d = rm.evaluate(make_signal(), bankroll_usd=1000, current_exposure_usd=0)
    assert d.approved and d.size_usd > 0


def test_rejects_thin_edge():
    rm = RiskManager(RiskConfig(min_edge=0.05))
    d = rm.evaluate(make_signal(edge=0.01), bankroll_usd=1000, current_exposure_usd=0)
    assert not d.approved


def test_rejects_low_confidence():
    rm = RiskManager(RiskConfig(min_confidence=0.6))
    d = rm.evaluate(make_signal(confidence=0.4), bankroll_usd=1000, current_exposure_usd=0)
    assert not d.approved


def test_exposure_cap_limits_size():
    rm = RiskManager(RiskConfig(max_total_exposure_fraction=0.5, max_position_fraction=1.0))
    # Already at 450 of a 500 budget -> only 50 left.
    d = rm.evaluate(make_signal(), bankroll_usd=1000, current_exposure_usd=450)
    assert d.approved and d.size_usd <= 50.0 + 1e-9


def test_exposure_cap_blocks_when_full():
    rm = RiskManager(RiskConfig(max_total_exposure_fraction=0.5))
    d = rm.evaluate(make_signal(), bankroll_usd=1000, current_exposure_usd=500)
    assert not d.approved


def test_drawdown_trips_kill_switch():
    rm = RiskManager(RiskConfig(bankroll_usd=1000, max_drawdown=0.2))
    rm.update_equity(1000)
    rm.update_equity(700)  # 30% drawdown
    assert rm.kill_switch_tripped
    d = rm.evaluate(make_signal(), bankroll_usd=700, current_exposure_usd=0)
    assert not d.approved


def test_consecutive_losses_trip_kill_switch():
    rm = RiskManager(RiskConfig(max_consecutive_losses=3))
    for _ in range(3):
        rm.record_trade_result(-10)
    assert rm.kill_switch_tripped


def test_a_win_resets_loss_streak():
    rm = RiskManager(RiskConfig(max_consecutive_losses=3))
    rm.record_trade_result(-10)
    rm.record_trade_result(-10)
    rm.record_trade_result(+50)
    assert rm.consecutive_losses == 0
    assert not rm.kill_switch_tripped


def test_reset_kill_switch():
    rm = RiskManager(RiskConfig(max_drawdown=0.1))
    rm.update_equity(1000)
    rm.update_equity(500)
    assert rm.kill_switch_tripped
    rm.reset_kill_switch()
    assert not rm.kill_switch_tripped
