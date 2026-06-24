# PolyBot — Polymarket Latency-Arbitrage Trading Bot

A clean, tested, **paper-trading-by-default** implementation of the
latency-arbitrage strategy described in the "*28 tools under the hood*" article:
exploit the lag between a fast exchange feed (Binance) and Polymarket's slower
re-pricing of short-duration BTC/ETH up/down contracts.

> ⚠️ **Read [DISCLAIMER.md](DISCLAIMER.md) first.** This is educational software.
> The bundled demo uses *synthetic* data and is an illustration of mechanics,
> not a promise of profit. Live trading can lose all your capital. It is off by
> default behind three independent safety gates.

---

## The idea in one paragraph

A 15-minute "Will BTC be higher at close?" contract trades in probability units
($0–$1, settling at $1 if true). When BTC moves sharply on Binance, the *real*
probability of the outcome shifts immediately, but Polymarket's order book — with
no dedicated market maker — re-prices a few seconds later. In that window the
fair value implied by the fast feed diverges from the price still shown on
Polymarket. The bot estimates fair value, measures the gap (the **edge**), sizes
the bet with **fractional Kelly**, and only trades when a **risk manager** with a
hard **kill switch** approves. The article's own conclusion: survival comes from
*risk management*, not forecasting. That is the part this codebase takes most
seriously.

## Quick start (no keys, no network, ~1 second)

```bash
git clone <this repo> && cd PolyBot-2026
python -m polybot demo          # self-contained paper-trading run on synthetic data
python -m polybot backtest -n 300
python -m polybot config        # show effective config (secrets redacted)
pip install pytest && python -m pytest -q   # 46 tests
```

Optional install as a CLI:

```bash
pip install -e .          # then just `polybot demo`
pip install -e ".[dev]"   # + pytest
```

Example demo output (synthetic — see disclaimer):

```
=== Paper-trading demo result ===
  trades:        28
  win rate:      71.4%
  realised PnL:  $...
  ROI:           +...%
  max drawdown:  20.9%
  kill switch:   True        <- the risk layer engaged and halted trading
```

## How the article's "6 layers / 28 tools" map to real code

The article lists 28 repositories across six layers. Most are interchangeable or
marketing. Stripped to what actually makes a working bot, here is the honest
mapping:

| Article layer | What it really needs | Where it lives here |
|---|---|---|
| **1 — Brain** (Claude, Qwen, Claude Squad…) | A reasoning step that can *veto/dampen* a trade. Edge comes from the model, not vibes. | `polybot/brain/reasoner.py` — optional `ClaudeBrain` (uses `claude-opus-4-8`) with a deterministic, dependency-free fallback. |
| **2 — Orchestration** (Agency Agents, TradingAgents…) | A loop that turns signals into risk-checked actions; a "risk manager veto." | `polybot/engine.py` (decision loop) + `polybot/risk/manager.py` (the veto). |
| **3 — Data & signals** (OpenBB, Binance collector, charts…) | A fast feed and the slow feed, plus a fair-value model. | `polybot/data/binance.py`, `polybot/data/polymarket.py`, `polybot/strategy/fair_value.py`. |
| **4 — Market intelligence** (Polyscope, whale trackers…) | Optional confluence signals. Not required for the core edge. | Hookable via the brain/strategy; intentionally not a hard dependency. |
| **5 — Backtest & simulation** (backtesting repos, polybot…) | Prove it on history before risking a cent. | `polybot/backtest/engine.py` + `polybot/demo.py`. |
| **6 — Execution** (py-clob-client) | Sign and place CLOB orders; paper-sim otherwise. | `polybot/execution/executor.py` (Paper + Live), `polybot/execution/portfolio.py`. |

## Architecture

```
Binance feed ─┐
              ├─► LatencyArbStrategy ─► Brain veto ─► RiskManager veto ─► Executor ─► Portfolio
Polymarket ───┘     (fair value vs        (sanity/      (Kelly size,      (paper/      (PnL,
  quotes            market price =         dampen)       limits,           live)        exposure)
                    edge)                                kill switch)
```

Every arrow is a separate, independently tested module. The strategy never
sizes; the risk manager never forecasts; the executor never decides. That
separation is what lets the kill switch be authoritative.

### Risk controls (defaults, all configurable in `polybot/config.py`)

- **Quarter-Kelly** sizing (`kelly_fraction=0.25`) — full Kelly is too violent
  under estimation error.
- **Per-position cap** at 10% of bankroll; **portfolio exposure cap** at 50%.
- **Minimum edge** (4%) and **minimum confidence** (0.55) to act at all.
- **Kill switch** on 20% drawdown from peak, or 8 consecutive losses.
- Timing filters: don't trade the first 30% of a window (genuinely uncertain) or
  the last 20 seconds (can't execute/settle cleanly).

## Going live (only if you accept you may lose everything)

Live trading is blocked unless **all three** are set:

```bash
export POLYBOT_LIVE=true
export POLYBOT_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK
export POLYMARKET_PRIVATE_KEY=0x...        # Polygon wallet, USDC settlement
pip install ".[live]"                       # py-clob-client + websockets
```

Even then, `polybot live` refuses to auto-start; you must wire concrete markets
and call `TradingEngine.run()` from your own script, so going live is always a
deliberate act. See `polybot/cli.py` and `polybot/engine.py`.

```python
from polybot import Config, TradingEngine
from polybot.models import Market

cfg = Config()                      # reads env; paper unless gates are set
engine = TradingEngine(cfg)
engine.track(Market(...))           # supply real market_id + token ids
engine.run(max_cycles=None)         # paper by default
```

## Project layout

```
polybot/
  config.py            # settings + the three-gate live-trading lock
  models.py            # dataclasses: Market, Signal, Order, Fill, Position...
  strategy/
    fair_value.py      # Binance move -> implied resolution probability (Normal CDF)
    kelly.py           # fractional Kelly sizing for binary contracts
    latency_arb.py     # edge detection (fair vs market), timing filters
  risk/manager.py      # limits + drawdown/streak kill switch (the veto)
  brain/reasoner.py    # optional Claude risk-veto + deterministic fallback
  data/
    binance.py         # fast feed (REST + optional websocket)
    polymarket.py      # Gamma metadata + CLOB order book (read-only)
  execution/
    executor.py        # PaperExecutor (default) + guarded LiveExecutor
    portfolio.py       # cash, positions, PnL, exposure, settlement
  backtest/engine.py   # replay scenarios through the live pipeline
  demo.py              # synthetic, deterministic scenario generator
  engine.py            # orchestration loop
  cli.py               # `polybot {demo,backtest,scan,config,paper,live}`
tests/                 # 46 unit tests, no network required
```

## Tests

```bash
python -m pytest -q     # 46 passed
```

Coverage spans fair-value math, Kelly sizing, risk/kill-switch behavior,
portfolio accounting, strategy edge detection and filters, the live-trading
safety gates, paper execution, and the full backtest + engine pipeline.

## License

MIT. Provided "as is" without warranty. See [DISCLAIMER.md](DISCLAIMER.md).
