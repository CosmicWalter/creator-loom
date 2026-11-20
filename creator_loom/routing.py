from __future__ import annotations

import json
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
        if card.adapter == "render" and not shutil.which("ffmpeg"):
            reasons.append("ffmpeg not installed")
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
