from polybot.config import Config
from polybot.execution.executor import PaperExecutor, build_executor, LiveExecutor
from polybot.models import Action, Order, Side


def test_live_blocked_by_default():
    cfg = Config()
    allowed, reason = cfg.can_trade_live()
    assert not allowed


def test_live_requires_all_gates(monkeypatch):
    cfg = Config()
    cfg.live_trading = True
    # Missing confirm token and key -> still blocked.
    assert not cfg.can_trade_live()[0]
    cfg.live_confirm = "I_UNDERSTAND_THE_RISK"
    assert not cfg.can_trade_live()[0]  # still no private key
    cfg.polymarket_private_key = "0xdeadbeef"
    assert cfg.can_trade_live()[0]


def test_build_executor_returns_paper_by_default():
    assert isinstance(build_executor(Config()), PaperExecutor)


def test_config_redacts_secrets():
    cfg = Config()
    cfg.polymarket_private_key = "0xsecret"
    cfg.anthropic_api_key = "sk-secret"
    d = cfg.to_dict()
    assert d["polymarket_private_key"].startswith("***")
    assert "0xsecret" not in d["polymarket_private_key"]
    assert d["anthropic_api_key"].startswith("***")
    assert "sk-secret" not in d["anthropic_api_key"]


def test_normalize_private_key_accepts_valid():
    import secrets
    from polybot.execution.executor import normalize_private_key

    raw = secrets.token_hex(32)            # 64 hex chars, no prefix
    assert normalize_private_key(raw) == "0x" + raw
    assert normalize_private_key("0x" + raw) == "0x" + raw
    assert normalize_private_key('  "0x' + raw + '"  ') == "0x" + raw  # quotes/space


def test_clob_client_version_tuple():
    from polybot.execution.executor import _version_tuple, MIN_CLOB_CLIENT

    assert _version_tuple("0.34.6") == (0, 34, 6)
    assert _version_tuple("0.1.13") == (0, 1, 13)
    assert _version_tuple("1.0.0rc1") == (1, 0, 0)   # tolerates suffixes
    assert _version_tuple("0.34.0") >= MIN_CLOB_CLIENT
    assert _version_tuple("0.1.13") < MIN_CLOB_CLIENT


def test_normalize_private_key_rejects_bad():
    import pytest
    from polybot.execution.executor import normalize_private_key

    for bad in ("0x...", "0xYOUR_KEY", "", "abc", "g" * 64, "12 word seed phrase here"):
        with pytest.raises(ValueError):
            normalize_private_key(bad)


def test_live_executor_refuses_to_build_when_gated():
    cfg = Config()  # paper mode
    try:
        LiveExecutor(cfg)
        assert False, "should have raised"
    except PermissionError:
        pass


def test_paper_executor_applies_slippage_and_fee():
    ex = PaperExecutor(slippage=0.01, fee_rate=0.02)
    order = Order("m", Side.UP, Action.BUY, size_usd=100, limit_price=0.50)
    fill = ex.submit(order)
    assert abs(fill.fill_price - 0.51) < 1e-9
    assert abs(fill.fee_usd - 2.0) < 1e-9


def test_paper_executor_ignores_non_buy():
    ex = PaperExecutor(0.0, 0.0)
    order = Order("m", Side.UP, Action.SELL, 100, 0.5)
    assert ex.submit(order) is None
