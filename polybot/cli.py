"""Command-line interface.

Subcommands:
  polybot config       Show the effective configuration (secrets redacted).
  polybot demo         Run a self-contained paper-trading demo (no network).
  polybot backtest     Run the bundled synthetic backtest scenario.
  polybot scan         Fetch live Polymarket markets (read-only; needs network).
  polybot paper        Live paper trade against real feeds (needs network).
  polybot live         Live trade for real (multi-gate opt-in; needs keys).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .config import load_config
from .demo import build_demo_scenarios, run_demo


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_config(args) -> int:
    cfg = load_config()
    print(json.dumps(cfg.to_dict(), indent=2, default=str))
    allowed, reason = cfg.can_trade_live()
    print(f"\nlive trading allowed: {allowed} ({reason})")
    return 0


def cmd_demo(args) -> int:
    result = run_demo()
    print("\n=== Paper-trading demo result ===")
    print(f"  trades:        {result.n_trades}")
    print(f"  win rate:      {result.win_rate:.1%}")
    print(f"  realised PnL:  ${result.realised_pnl:,.2f}")
    print(f"  final equity:  ${result.final_equity:,.2f}")
    print(f"  ROI:           {result.roi:+.1%}")
    print(f"  max drawdown:  {result.max_drawdown:.1%}")
    print(f"  fees paid:     ${result.fees_paid:,.2f}")
    print(f"  kill switch:   {result.kill_switch_tripped}")
    return 0


def cmd_backtest(args) -> int:
    from .backtest.engine import Backtester

    cfg = load_config()
    scenarios = build_demo_scenarios(n=args.n, config=cfg)
    result = Backtester(cfg).run(scenarios)
    print(f"backtest over {len(scenarios)} markets:")
    print(f"  trades={result.n_trades} win_rate={result.win_rate:.1%} "
          f"ROI={result.roi:+.1%} final=${result.final_equity:,.2f} "
          f"maxDD={result.max_drawdown:.1%} kill={result.kill_switch_tripped}")
    return 0


def cmd_scan(args) -> int:
    from .data.polymarket import PolymarketData

    cfg = load_config()
    pm = PolymarketData(cfg.polymarket_clob_url, cfg.polymarket_gamma_url)
    try:
        markets = pm.list_markets(limit=args.limit)
    except Exception as e:
        print(f"failed to fetch markets: {e}", file=sys.stderr)
        return 1
    for m in markets[: args.limit]:
        q = m.get("question") or m.get("title") or m.get("slug", "?")
        print(f"- {q}")
    print(f"\n{len(markets)} markets fetched.")
    return 0


def _run_live_runner(cfg, cycles: Optional[int]) -> int:
    from .live_runner import LiveRunner

    runner = LiveRunner(cfg)
    allowed, reason = cfg.can_trade_live()
    mode = "LIVE" if allowed else "PAPER"
    print(f"Starting {mode} trading loop against live Polymarket data "
          f"(Ctrl-C to stop)...")
    try:
        runner.run(max_cycles=cycles)
    except KeyboardInterrupt:
        print("\nstopped by user")
    p = runner.engine.portfolio
    print(f"\nequity=${p.equity_usd():,.2f} realisedPnL=${p.realised_pnl:,.2f} "
          f"open={len(p.positions)} fees=${p.fees_paid_usd:,.2f} "
          f"killswitch={runner.engine.risk.kill_switch_tripped}")
    return 0


def cmd_paper(args) -> int:
    """Paper-trade against REAL live Polymarket + Binance data. No keys, no risk."""
    cfg = load_config()
    # Force paper regardless of env, so `paper` is always safe.
    cfg.live_trading = False
    return _run_live_runner(cfg, args.cycles)


def cmd_live(args) -> int:
    cfg = load_config()
    allowed, reason = cfg.can_trade_live()
    if not allowed:
        print(f"LIVE TRADING BLOCKED: {reason}", file=sys.stderr)
        print("\nTo enable (only if you accept full financial risk):", file=sys.stderr)
        print("  export POLYBOT_LIVE=true", file=sys.stderr)
        print("  export POLYBOT_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK", file=sys.stderr)
        print("  export POLYMARKET_PRIVATE_KEY=0x...", file=sys.stderr)
        print("  pip install '.[live]'", file=sys.stderr)
        print("\nThen re-run `polybot live`. Test with `polybot paper` first.", file=sys.stderr)
        return 1
    if not args.yes:
        print("About to trade REAL money on Polymarket. Re-run with --yes to confirm.",
              file=sys.stderr)
        return 1
    return _run_live_runner(cfg, args.cycles)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="polybot", description="Polymarket latency-arbitrage bot")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="show effective configuration").set_defaults(func=cmd_config)
    sub.add_parser("demo", help="run a self-contained paper-trading demo").set_defaults(func=cmd_demo)

    bt = sub.add_parser("backtest", help="run the bundled backtest")
    bt.add_argument("-n", type=int, default=200, help="number of synthetic markets")
    bt.set_defaults(func=cmd_backtest)

    sc = sub.add_parser("scan", help="fetch live Polymarket markets (read-only)")
    sc.add_argument("--limit", type=int, default=20)
    sc.set_defaults(func=cmd_scan)

    pa = sub.add_parser("paper", help="paper trade against REAL live feeds (no keys/risk)")
    pa.add_argument("--cycles", type=int, default=None, help="stop after N loop cycles (default: run forever)")
    pa.set_defaults(func=cmd_paper)

    lv = sub.add_parser("live", help="live trade for real money (multi-gate opt-in)")
    lv.add_argument("--cycles", type=int, default=None, help="stop after N loop cycles")
    lv.add_argument("--yes", action="store_true", help="confirm real-money trading")
    lv.set_defaults(func=cmd_live)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
