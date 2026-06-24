import os

from polybot.config import load_dotenv


def test_load_dotenv_sets_unset_vars(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "POLYBOT_LIVE=true\n"
        'POLYMARKET_PRIVATE_KEY="0xABC"\n'
        "export POLYBOT_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK\n"
    )
    for k in ("POLYBOT_LIVE", "POLYMARKET_PRIVATE_KEY", "POLYBOT_LIVE_CONFIRM"):
        monkeypatch.delenv(k, raising=False)

    n = load_dotenv(str(env))
    assert n == 3
    assert os.environ["POLYBOT_LIVE"] == "true"
    assert os.environ["POLYMARKET_PRIVATE_KEY"] == "0xABC"   # quotes stripped
    assert os.environ["POLYBOT_LIVE_CONFIRM"] == "I_UNDERSTAND_THE_RISK"  # export stripped


def test_load_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("POLYBOT_LIVE=false\n")
    monkeypatch.setenv("POLYBOT_LIVE", "true")  # real env should win
    load_dotenv(str(env))
    assert os.environ["POLYBOT_LIVE"] == "true"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(str(tmp_path / "nope.env")) == 0
