"""Allowlisted provider usage and explicitly estimated token costs."""

import json
from pathlib import Path


def provider_usage(payload):
    usage = payload.get("usage")
    if usage is None:
        return {"status": "not_reported"}
    if not isinstance(usage, dict):
        return {"status": "invalid"}
    keys = ["prompt_tokens", "completion_tokens"]
    if any(type(usage.get(k)) is not int or not 0 <= usage[k] <= 1000000000 for k in keys):
        return {"status": "invalid"}
    return {"status": "provider_reported", "input_tokens": usage["prompt_tokens"],
            "output_tokens": usage["completion_tokens"]}


def estimate(card, directory: Path):
    result = {"status": "not_reported", "token_cost_estimate": None}
    path = directory / "provider-usage.json"
    if not path.exists():
        return result
    # Revalidate the sidecar before using it for accounting. External adapters
    # cannot inject arbitrary response fields into persistent measurements.
    try:
        raw = json.loads(path.read_text())
        if raw.get("status") != "provider_reported":
            result["status"] = "invalid" if raw.get("status") == "invalid" else "not_reported"
            return result
        result = {**provider_usage({"usage": {"prompt_tokens": raw.get("input_tokens"),
                                               "completion_tokens": raw.get("output_tokens")}}),
                  "token_cost_estimate": None}
    except (ValueError, TypeError, AttributeError):
        return {"status": "invalid", "token_cost_estimate": None}
    if result["status"] == "provider_reported" and card.input_price_per_million is not None:
        result["token_cost_estimate"] = (result["input_tokens"] * card.input_price_per_million +
                                         result["output_tokens"] * card.output_price_per_million) / 1000000
        result["rate_source"] = "frozen_model_card"
    return result
