"""PolyBot — a latency-arbitrage trading bot framework for Polymarket.

Educational / research software. Paper trading by default; live trading is an
explicit, multi-gate opt-in. Trading involves substantial risk of loss. See
README and DISCLAIMER before using with real funds.
"""

from .config import Config, load_config
from .engine import TradingEngine
from .models import Action, Market, MarketQuote, PricePoint, Side, Signal

__version__ = "0.1.0"

__all__ = [
    "Config",
    "load_config",
    "TradingEngine",
    "Market",
    "MarketQuote",
    "PricePoint",
    "Signal",
    "Side",
    "Action",
    "__version__",
]
