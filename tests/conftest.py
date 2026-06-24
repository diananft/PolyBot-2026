import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    """Snapshot os.environ before each test and restore it after.

    Some tests (and the .env loader) mutate process environment variables.
    Without this, a leaked POLYMARKET_* / POLYBOT_LIVE could arm the live gate
    in an unrelated test and try to build a real executor. Isolate every test.
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
