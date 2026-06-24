"""Discovery parsing tests against the real Gamma schema (no network)."""

from polybot.discovery import (
    build_market,
    infer_underlying,
    is_short_duration_crypto,
    markets_from_event,
    parse_iso8601,
    parse_window_seconds,
)
from polybot.models import Side


def _raw(**over):
    base = {
        "id": "999",
        "question": "Will Bitcoin be higher at 3:00pm? (up or down)",
        "clobTokenIds": '["111", "222"]',          # JSON-string array, like prod
        "outcomes": '["Yes", "No"]',
        "startDate": "2026-06-24T14:00:00Z",
        "endDate": "2026-06-24T14:15:00Z",
    }
    base.update(over)
    return base


def test_parse_iso8601_z_suffix():
    ts = parse_iso8601("2026-06-24T14:00:00Z")
    assert ts is not None and ts > 0


def test_parse_iso8601_bad_returns_none():
    assert parse_iso8601("not-a-date") is None
    assert parse_iso8601("") is None


def test_infer_underlying():
    assert infer_underlying("Will Bitcoin go up?") == "BTCUSDT"
    assert infer_underlying("ETH higher by close?") == "ETHUSDT"
    assert infer_underlying("Who wins the election?") is None


def test_build_market_maps_yes_to_up():
    m = build_market(_raw(), open_price=60000.0)
    assert m is not None
    assert m.underlying == "BTCUSDT"
    assert m.up_token_id == "111"      # Yes
    assert m.down_token_id == "222"    # No
    assert m.open_price == 60000.0
    assert m.close_ts > m.open_ts


def test_build_market_handles_list_token_ids():
    # Some responses give real lists rather than JSON strings.
    m = build_market(_raw(clobTokenIds=["a", "b"], outcomes=["Yes", "No"]), open_price=1.0)
    assert m is not None and m.up_token_id == "a" and m.down_token_id == "b"


def test_build_market_rejects_non_crypto():
    assert build_market(_raw(question="Who wins?"), open_price=1.0) is None


def test_build_market_rejects_missing_tokens():
    assert build_market(_raw(clobTokenIds="[]"), open_price=1.0) is None


def test_build_market_rejects_bad_window():
    bad = _raw(endDate="2026-06-24T13:00:00Z")  # ends before it starts
    assert build_market(bad, open_price=1.0) is None


def test_parse_window_seconds():
    assert parse_window_seconds("Bitcoin Up or Down - June 25, 10:30AM-10:45AM ET") == 15 * 60
    assert parse_window_seconds("Ethereum Up or Down - 10:30AM-10:35AM ET") == 5 * 60
    # PM wrap and hour boundary.
    assert parse_window_seconds("BTC 11:55AM-12:00PM ET") == 5 * 60
    assert parse_window_seconds("no times here") is None


def test_is_short_duration_crypto():
    title = "Bitcoin Up or Down - 10:30AM-10:45AM ET"
    assert is_short_duration_crypto(title, 15 * 60, max_window_s=3600) is True
    # Too long.
    assert is_short_duration_crypto(title, 2 * 3600, max_window_s=3600) is False
    # Non-crypto.
    assert is_short_duration_crypto("Who wins? 1:00PM-1:15PM", 15 * 60, 3600) is False
    # No window.
    assert is_short_duration_crypto(title, None, 3600) is False


def test_markets_from_event_anchors_window_to_close():
    event = {
        "title": "Bitcoin Up or Down - June 25, 10:30AM-10:45AM ET",
        "markets": [{
            "id": "evt-mkt-1",
            "question": "Bitcoin Up or Down - June 25, 10:30AM-10:45AM ET",
            "clobTokenIds": '["up-tok", "down-tok"]',
            "outcomes": '["Up", "Down"]',
            # startDate here is deploy time, deliberately far from the window.
            "startDate": "2026-06-24T14:38:07Z",
            "endDate": "2026-06-25T14:45:00Z",
        }],
    }
    tuples = markets_from_event(event, max_window_s=3600)
    assert len(tuples) == 1
    raw, underlying, open_ts, close_ts = tuples[0]
    assert underlying == "BTCUSDT"
    # Window is 15 min anchored to the close, NOT the deploy-time startDate.
    assert abs((close_ts - open_ts) - 15 * 60) < 1e-6
    m = build_market(raw, open_price=60000.0, underlying=underlying,
                     open_ts=open_ts, close_ts=close_ts)
    assert m is not None
    assert m.up_token_id == "up-tok" and m.down_token_id == "down-tok"
    assert abs(m.close_ts - m.open_ts - 15 * 60) < 1e-6
