from polybot.strategy.kelly import kelly_fraction, position_size_usd


def test_no_edge_is_zero():
    # Fair odds: win_prob == price means zero expected edge, zero stake.
    assert abs(kelly_fraction(win_prob=0.5, price=0.5)) < 1e-12


def test_positive_edge_positive_fraction():
    f = kelly_fraction(win_prob=0.6, price=0.5)
    assert f > 0


def test_negative_edge_clamped_to_zero():
    f = kelly_fraction(win_prob=0.4, price=0.5)
    assert f == 0.0


def test_kelly_formula_value():
    # price=0.5 -> b=1. f* = (b*p - q)/b = p - q = 2p - 1.
    assert abs(kelly_fraction(0.6, 0.5) - 0.2) < 1e-9


def test_degenerate_prices_zero():
    assert kelly_fraction(0.9, 0.0) == 0.0
    assert kelly_fraction(0.9, 1.0) == 0.0


def test_position_size_respects_cap():
    size = position_size_usd(
        win_prob=0.95, price=0.5, bankroll_usd=1000,
        kelly_fraction_used=1.0, max_position_fraction=0.10,
    )
    assert size == 100.0  # capped at 10% of bankroll


def test_fractional_kelly_scales():
    full = position_size_usd(0.6, 0.5, 1000, 1.0, 1.0)
    quarter = position_size_usd(0.6, 0.5, 1000, 0.25, 1.0)
    assert abs(quarter - full * 0.25) < 1e-9
