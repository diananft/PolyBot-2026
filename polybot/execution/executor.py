"""Order execution: paper (default) and live (opt-in) executors.

The PaperExecutor simulates fills with configurable slippage and fees and never
touches the network. The LiveExecutor wraps ``py-clob-client`` and is only
constructable when the Config's live-trading gate is satisfied — and even then
it refuses to send anything unless that gate passes at call time too.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from ..config import Config
from ..models import Action, Fill, Order

log = logging.getLogger("polybot.executor")


class Executor(Protocol):
    def submit(self, order: Order) -> Optional[Fill]:
        ...


class PaperExecutor:
    """Simulated execution. Assumes we cross the spread and pay fees."""

    def __init__(self, slippage: float, fee_rate: float):
        self.slippage = slippage
        self.fee_rate = fee_rate

    def submit(self, order: Order) -> Optional[Fill]:
        if order.action is not Action.BUY:
            # This bot only opens long binary positions; selling is modelled via
            # settlement in the Portfolio.
            return None
        # Pay up to slippage worse than our limit, but never above 1.0.
        fill_price = min(1.0, order.limit_price + self.slippage)
        if fill_price <= 0:
            return None
        fee = order.size_usd * self.fee_rate
        log.info(
            "PAPER fill %s %s $%.2f @ %.3f (fee $%.2f)",
            order.market_id, order.side.value, order.size_usd, fill_price, fee,
        )
        return Fill(order=order, fill_price=fill_price, size_usd=order.size_usd, fee_usd=fee)


class LiveExecutor:
    """Real execution via the Polymarket CLOB. Heavily guarded.

    Importing/using py_clob_client is lazy so the package works without it
    installed. This path is never reached unless ``Config.can_trade_live()``
    returns True at construction *and* submission time.
    """

    def __init__(self, config: Config):
        allowed, reason = config.can_trade_live()
        if not allowed:
            raise PermissionError(f"refusing to build LiveExecutor: {reason}")
        self.config = config
        self._client = self._build_client()

    def _build_client(self):
        try:
            from py_clob_client.client import ClobClient  # type: ignore
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "py-clob-client is required for live trading: pip install py-clob-client"
            ) from e
        cfg = self.config
        # Polygon mainnet, chain id 137, USDC settlement. signature_type/funder
        # select the wallet model (EOA vs email/proxy).
        kwargs = dict(key=cfg.polymarket_private_key, chain_id=137,
                      signature_type=cfg.polymarket_signature_type)
        if cfg.polymarket_funder:
            kwargs["funder"] = cfg.polymarket_funder
        client = ClobClient(cfg.polymarket_clob_url, **kwargs)
        # L2 auth: derive (or create) the API credentials needed to post orders.
        client.set_api_creds(client.create_or_derive_api_creds())
        return client

    def _order_type(self):  # pragma: no cover - network
        from py_clob_client.clob_types import OrderType  # type: ignore
        return getattr(OrderType, self.config.order_type, OrderType.FAK)

    def submit(self, order: Order) -> Optional[Fill]:  # pragma: no cover - network
        allowed, reason = self.config.can_trade_live()
        if not allowed:
            log.error("live submit blocked: %s", reason)
            return None
        from py_clob_client.clob_types import OrderArgs  # type: ignore
        from py_clob_client.order_builder.constants import BUY  # type: ignore

        # Translate USD notional into share quantity at our limit price.
        size_shares = order.size_usd / order.limit_price if order.limit_price > 0 else 0
        if size_shares <= 0:
            return None
        args = OrderArgs(
            price=round(order.limit_price, 3),
            size=round(size_shares, 2),
            side=BUY,
            token_id=order.token_id,
        )
        try:
            signed = self._client.create_order(args)
            resp = self._client.post_order(signed, self._order_type())
        except Exception as e:
            log.error("LIVE order failed for %s: %s", order.market_id, e)
            return None
        log.info("LIVE order response: %s", resp)
        # Only record a fill if the venue accepted the order.
        if not isinstance(resp, dict) or not resp.get("success", False):
            log.warning("LIVE order not accepted: %s", resp)
            return None
        # Reconciliation of the exact matched size happens at settlement; record
        # the requested notional at our limit and let settlement correct PnL.
        fee = order.size_usd * self.config.risk.fee_rate
        return Fill(order=order, fill_price=order.limit_price, size_usd=order.size_usd, fee_usd=fee)


def build_executor(config: Config) -> Executor:
    """Factory: returns a LiveExecutor only when the gate is fully satisfied."""
    allowed, reason = config.can_trade_live()
    if allowed:
        log.warning("LIVE TRADING ENABLED — real orders will be submitted")
        return LiveExecutor(config)
    log.info("paper trading mode (%s)", reason)
    return PaperExecutor(config.risk.slippage, config.risk.fee_rate)
