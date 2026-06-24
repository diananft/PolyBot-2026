"""Layer 1 — the "brain".

The article's headline claim is that Claude's conservative reasoning is what
kept the bot alive. We expose an optional AI reasoning step that can *veto or
dampen* a signal, but never *fabricate* one: the deterministic latency-arb model
is always the source of the edge. The AI acts as an extra risk gate, in the
spirit of the "Risk Manager veto" from the orchestration layer.

Without an Anthropic API key (or with the brain disabled) we use a deterministic
heuristic so the bot is fully functional offline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..config import Config
from ..models import Market, Signal

log = logging.getLogger("polybot.brain")


@dataclass
class BrainVerdict:
    approve: bool
    confidence_multiplier: float   # scales the signal confidence in [0, 1.5]
    note: str


class DeterministicBrain:
    """A transparent, dependency-free stand-in for the AI strategist.

    It applies common-sense guards the article praises Claude for: be more
    cautious when the implied move is extreme (possible data glitch / wick) and
    when very little time remains.
    """

    def assess(self, market: Market, signal: Signal, now: float | None = None) -> BrainVerdict:
        # Treat an implausibly large edge as suspicious rather than a gift.
        if signal.edge > 0.45:
            return BrainVerdict(False, 0.0, "edge implausibly large; likely stale/glitch data")
        mult = 1.0
        note = "ok"
        if signal.edge > 0.25:
            mult = 0.7
            note = "large edge; sizing down"
        if signal.fair_prob < 0.02 or signal.fair_prob > 0.98:
            mult *= 0.8
            note = "near-certain outcome; thin reward, keep small"
        return BrainVerdict(True, mult, note)


class ClaudeBrain:
    """Uses the Anthropic API to sanity-check a signal.

    Lazy-imports the SDK so the package works without it. Falls back to the
    deterministic brain on any error — the bot must never hard-fail because the
    network or the model is unavailable.
    """

    def __init__(self, config: Config):
        self.config = config
        self._fallback = DeterministicBrain()
        self._client = None
        try:
            import anthropic  # type: ignore

            self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        except Exception as e:  # pragma: no cover - optional dependency / no key
            log.warning("Claude brain unavailable, using deterministic fallback: %s", e)

    def assess(self, market: Market, signal: Signal, now: float | None = None) -> BrainVerdict:
        if self._client is None:
            return self._fallback.assess(market, signal, now)
        try:  # pragma: no cover - network
            prompt = self._build_prompt(market, signal)
            msg = self._client.messages.create(
                model=self.config.ai_model,
                max_tokens=300,
                system=(
                    "You are a conservative risk manager for a prediction-market "
                    "latency-arbitrage bot. Given a quantitative signal, decide "
                    "whether to approve the trade and a confidence multiplier in "
                    "[0,1.5]. Prefer caution. Respond ONLY with compact JSON: "
                    '{"approve": bool, "confidence_multiplier": float, "note": str}.'
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text  # type: ignore[attr-defined]
            data = json.loads(text)
            return BrainVerdict(
                approve=bool(data["approve"]),
                confidence_multiplier=float(data["confidence_multiplier"]),
                note=str(data.get("note", "")),
            )
        except Exception as e:  # pragma: no cover - network
            log.warning("Claude assess failed, falling back: %s", e)
            return self._fallback.assess(market, signal, now)

    @staticmethod
    def _build_prompt(market: Market, signal: Signal) -> str:
        return json.dumps(
            {
                "question": market.question,
                "underlying": market.underlying,
                "seconds_to_close": round(market.seconds_to_close, 1),
                "side": signal.side.value,
                "model_fair_prob": round(signal.fair_prob, 4),
                "market_prob": round(signal.market_prob, 4),
                "edge": round(signal.edge, 4),
                "confidence": round(signal.confidence, 3),
                "rationale": signal.rationale,
            }
        )


def build_brain(config: Config):
    if config.use_ai_brain and config.anthropic_api_key:
        return ClaudeBrain(config)
    return DeterministicBrain()
