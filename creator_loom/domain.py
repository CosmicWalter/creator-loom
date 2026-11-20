from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


def bounded(value: float, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return float(value)


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise ValueError("IDs must contain 1–64 letters, digits, underscores or hyphens")
    return value


@dataclass(frozen=True)
class ModelCard:
    id: str
    capability: str
    adapter: str
    model: str = ""
    endpoint: str = ""
    api_key_env: str = ""
    local: bool = False
    quality: float = 0.5
    cost: float = 0.0
    latency: float = 1.0
    max_chars: int = 12000
    languages: tuple[str, ...] = ("*",)
    enabled: bool = True

    def __post_init__(self):
        identifier(self.id)
        if self.capability not in {"text", "image", "audio", "video"}:
            raise ValueError("Unknown capability")
        adapters = {"chat": "text", "image": "image", "speech": "audio",
                    "cover": "image", "render": "video"}
        if adapters.get(self.adapter) != self.capability:
            raise ValueError("Adapter does not implement this capability")
        bounded(self.quality, 0, 1, "quality")
        bounded(self.cost, 0, 100000, "cost")
        bounded(self.latency, 0, 86400, "latency")
        if not isinstance(self.local, bool) or not isinstance(self.enabled, bool):
            raise ValueError("local and enabled must be booleans")
        if type(self.max_chars) is not int or not 1 <= self.max_chars <= 1000000:
            raise ValueError("Invalid max_chars")
        if not self.languages or any(not isinstance(x, str) for x in self.languages):
            raise ValueError("languages must be a nonempty list of strings")
        if self.adapter in {"chat", "image", "speech"}:
            u = urlsplit(self.endpoint)
            loopback = u.hostname in {"localhost", "127.0.0.1", "::1"}
            if u.username or u.password or u.query or u.fragment:
                raise ValueError("Endpoint must not contain credentials, query or fragment")
            if u.scheme != "https" and not (u.scheme == "http" and loopback):
                raise ValueError("Use HTTPS or loopback HTTP")
            if self.local and not loopback:
                raise ValueError("Local model endpoints must be loopback addresses")
            if not self.model:
                raise ValueError("Remote adapters require a model name")
            if self.api_key_env and not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.api_key_env):
                raise ValueError("api_key_env must name an environment variable")
        elif not self.local or self.cost != 0:
            raise ValueError("Built-in local tools must be local and zero-cost")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Brief:
    topic: str
    format: str = "article"
    language: str = "zh"
    profile: str = "default"
    budget: float = 1.0
    local_only: bool = False
    max_latency: float = 300.0

    def __post_init__(self):
        if not isinstance(self.topic, str) or not self.topic.strip() or len(self.topic) > 10000:
            raise ValueError("Topic must contain 1–10000 characters")
        if self.format not in RECIPES:
            raise ValueError("Unknown creation format")
        identifier(self.profile)
        if not re.fullmatch(r"[a-zA-Z-]{2,20}", self.language):
            raise ValueError("Invalid language")
        bounded(self.budget, 0, 100000, "budget")
        bounded(self.max_latency, 0, 86400, "max_latency")
        if not isinstance(self.local_only, bool):
            raise ValueError("local_only must be a boolean")


# Dependencies refer to immutable outputs, not hidden global project state.
RECIPES = {
    "article": [("draft", "text", [])],
    "novel": [("outline", "text", []), ("chapter", "text", ["outline"])],
    "cover": [("cover", "image", [])],
    "podcast": [("script", "text", []), ("narration", "audio", ["script"])],
    "bookcast": [("script", "text", []), ("cover", "image", []),
                 ("narration", "audio", ["script"]), ("film", "video", ["cover", "narration"])],
    "talkshow": [("script", "text", []), ("cover", "image", []),
                 ("narration", "audio", ["script"]), ("film", "video", ["cover", "narration"])],
    "meme": [("caption", "text", []), ("cover", "image", ["caption"])],
}


@dataclass
class Decision:
    selected: str
    score: float
    candidates: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
