from __future__ import annotations

import json
import itertools
import math
import os
import shutil
from pathlib import Path

from .domain import Decision, ModelCard


def load_cards(path: Path | None) -> list[ModelCard]:
    defaults = [
        ModelCard("local-cover", "image", "cover", local=True, quality=0.35, latency=0.1),
        ModelCard("local-render", "video", "render", local=True, quality=0.8, latency=30),
    ]
    if not path:
        return defaults
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or set(data) != {"models"} or not isinstance(data["models"], list):
        raise ValueError("Configuration must contain a models array")
    cards = defaults + [ModelCard(**{**m, "languages": tuple(m.get("languages", ["*"]))}) for m in data["models"]]
    if len({m.id for m in cards}) != len(cards):
        raise ValueError("Model IDs must be unique, including built-ins")
    return cards


def choose(cards, store, *, profile, capability, language, chars, budget, local_only, max_latency):
    accepted, rejected = [], []
    for card in cards:
        reasons = []
        if card.capability != capability:
            continue
        if not card.enabled:
            reasons.append("disabled")
        if local_only and not card.local:
            reasons.append("requires sending content off-device")
        if card.cost > budget + 1e-9:
            reasons.append("configured cost estimate exceeds remaining budget")
        if card.latency > max_latency:
            reasons.append("configured latency exceeds remaining target")
        if chars > card.max_chars:
            reasons.append("input exceeds character limit")
        if "*" not in card.languages and language not in card.languages:
            reasons.append("language unsupported")
        if card.api_key_env and not os.environ.get(card.api_key_env):
            reasons.append("credential environment variable missing")
        if card.adapter == "render" and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            reasons.append("ffmpeg or ffprobe not installed")
        if reasons:
            rejected.append({"model": card.id, "reasons": reasons})
            continue
        ratings = store.observations(profile, capability, card.id)
        # Four prior observations keep one click from overwhelming initial estimates.
        quality = (4 * card.quality + sum(ratings)) / (4 + len(ratings))
        economy = 1 - card.cost / max(budget, card.cost, 0.000001)
        speed = 1 - card.latency / max(max_latency, card.latency, 0.000001)
        score = 0.75 * quality + 0.15 * economy + 0.1 * speed
        accepted.append({"model": card.id, "score": round(score, 8), "quality": quality,
                         "feedback_count": len(ratings), "configured_cost": card.cost,
                         "configured_latency": card.latency})
    if not accepted:
        raise ValueError(f"No eligible {capability} model: {json.dumps(rejected, ensure_ascii=False)}")
    accepted.sort(key=lambda x: (-x["score"], x["model"]))
    return Decision(accepted[0]["model"], accepted[0]["score"], accepted, rejected)


def allocate(cards, store, brief, requests):
    """Find the best feasible joint allocation for a small explicit workflow.

    Every step is scored against the same total budget/latency normalization.
    Exhaustive search gives a reproducible optimum under those estimates, not
    a claim that self-reported model priors predict actual creative quality.
    """
    decisions = [choose(cards, store, profile=brief.profile, capability=r["capability"],
                        language=brief.language, chars=r["chars"], budget=brief.budget,
                        local_only=brief.local_only, max_latency=brief.max_latency)
                 for r in requests]
    combinations = math.prod(len(d.candidates) for d in decisions)
    if combinations > 1000000:
        raise ValueError("Model catalog creates more than one million allocations; narrow enabled models")
    by_id = {m.id: m for m in cards}
    best, best_key, feasible = None, None, 0
    for options in itertools.product(*(d.candidates for d in decisions)):
        cost = sum(by_id[o["model"]].cost for o in options)
        latency = sum(by_id[o["model"]].latency for o in options)
        if cost > brief.budget + 1e-9 or latency > brief.max_latency + 1e-9:
            continue
        feasible += 1
        score = sum(o["score"] for o in options)
        key = (-score, cost, latency, tuple(o["model"] for o in options))
        if best_key is None or key < best_key:
            best, best_key = options, key
    if best is None:
        raise ValueError("No complete workflow fits the configured total budget and latency estimates")
    for decision, option in zip(decisions, best):
        decision.selected = option["model"]
        decision.score = option["score"]
    return decisions, {"method": "exact joint allocation under configured estimates",
                       "combinations": combinations, "feasible": feasible,
                       "total_score": -best_key[0]}
