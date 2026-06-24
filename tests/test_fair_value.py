import math

from polybot.strategy.fair_value import up_probability, confidence_from_inputs


def test_at_the_money_is_half():
    # No move, symmetric: probability of finishing up is ~0.5.
    p = up_probability(open_price=100.0, current_price=100.0, seconds_to_close=300, minute_vol=0.004)
    assert abs(p - 0.5) < 1e-9


def test_move_up_increases_up_prob():
    p = up_probability(100.0, 100.5, seconds_to_close=60, minute_vol=0.004)
    assert p > 0.5


def test_move_down_decreases_up_prob():
    p = up_probability(100.0, 99.5, seconds_to_close=60, minute_vol=0.004)
    assert p < 0.5


def test_less_time_left_means_more_extreme():
    # Same move, but with less time to revert the probability should be more
    # confident (further from 0.5).
    near = up_probability(100.0, 100.5, seconds_to_close=30, minute_vol=0.004)
    far = up_probability(100.0, 100.5, seconds_to_close=600, minute_vol=0.004)
    assert near > far > 0.5


def test_zero_time_resolves_by_sign():
    assert up_probability(100.0, 101.0, 0, 0.004) == 1.0
    assert up_probability(100.0, 99.0, 0, 0.004) == 0.0


def test_probability_bounds():
    for cur in (50.0, 99.0, 100.0, 101.0, 200.0):
        p = up_probability(100.0, cur, 120, 0.004)
        assert 0.0 <= p <= 1.0


def test_invalid_prices_neutral():
    assert up_probability(0.0, 100.0, 60, 0.004) == 0.5
    assert up_probability(100.0, 0.0, 60, 0.004) == 0.5


def test_confidence_penalises_final_seconds():
    high = confidence_from_inputs(seconds_to_close=120, fraction_elapsed=0.9)
    low = confidence_from_inputs(seconds_to_close=5, fraction_elapsed=0.9)
    assert high > low
