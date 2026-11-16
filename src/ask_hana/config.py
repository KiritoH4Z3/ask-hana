"""Settings from the environment, and the fail-closed provider resolution."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .errors import ConfigError, safe_url

log = logging.getLogger("ask_hana.config")

PROVIDERS = ("auto", "claude", "ollama", "extractive")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# The Claude settings carry the ASK_HANA_ prefix on purpose: Claude Code exports its own
# CLAUDE_EFFORT into every shell it opens, and reading that would hijack this app's setting.


@dataclass(frozen=True)
class Settings:
    provider: str = "auto"
    anthropic_api_key: str | None = field(default=None, repr=False)
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str | None = None
    knowledge_dir: Path = Path("./knowledge")
    chroma_path: Path = Path("./data/chroma")
    top_k: int = 4
    min_score: float = 0.33
    rate_limit_per_minute: int = 12
    provider_timeout_s: float = 60.0
    host: str = "127.0.0.1"
    port: int = 3012


@dataclass(frozen=True)
class Resolved:
    mode: str
    model: str | None
    reason: str


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _number(env: Mapping[str, str], name: str, default, cast, lo, hi, hint: str):
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(
            f"{name} must be a number ({hint}), got {raw!r}. Fix it in .env."
        ) from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi} ({hint}), got {raw!r}.")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings once. With env=None, `.env` is loaded first and os.environ is used."""
    if env is None:
        load_dotenv(override=False)
        env = os.environ

    provider = (_get(env, "ASK_HANA_PROVIDER") or "auto").lower()
    if provider not in PROVIDERS:
        raise ConfigError(
            f"ASK_HANA_PROVIDER must be one of {', '.join(PROVIDERS)}, got {provider!r}. "
            "Fix it in .env."
        )
    effort = (_get(env, "ASK_HANA_CLAUDE_EFFORT") or "low").lower()
    if effort not in EFFORTS:
        raise ConfigError(
            f"ASK_HANA_CLAUDE_EFFORT must be one of {', '.join(EFFORTS)}, got {effort!r}. "
            "Fix it in .env."
        )

    return Settings(
        provider=provider,
        anthropic_api_key=_get(env, "ANTHROPIC_API_KEY"),
        claude_model=_get(env, "ASK_HANA_CLAUDE_MODEL") or Settings.claude_model,
        claude_effort=effort,
        ollama_url=(_get(env, "OLLAMA_URL") or Settings.ollama_url).rstrip("/"),
        ollama_model=_get(env, "OLLAMA_MODEL"),
        knowledge_dir=Path(_get(env, "KNOWLEDGE_DIR") or "./knowledge"),
        chroma_path=Path(_get(env, "CHROMA_PATH") or "./data/chroma"),
        top_k=_number(env, "TOP_K", 4, int, 1, 8, "how many passages to retrieve"),
        min_score=_number(
            env, "MIN_SCORE", Settings.min_score, float, 0.0, 1.0, "similarity floor"
        ),
        rate_limit_per_minute=_number(
            env, "RATE_LIMIT_PER_MINUTE", 12, int, 1, 10_000, "requests per client per minute"
        ),
        provider_timeout_s=_number(
            env, "PROVIDER_TIMEOUT_S", 60.0, float, 1.0, 600.0, "seconds to wait for a model"
        ),
        host=_get(env, "HOST") or "127.0.0.1",
        port=_number(env, "PORT", 3012, int, 1, 65535, "a TCP port"),
    )


def ollama_has_model(url: str, model: str, timeout: float = 1.0) -> bool:
    """True when `GET {url}/api/tags` lists the model. Any failure means False."""
    try:
        reply = httpx.get(f"{url}/api/tags", timeout=timeout)
        reply.raise_for_status()
        names = {m.get("name") for m in reply.json().get("models", [])}
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return model in names or f"{model}:latest" in names


def resolve_provider(
    settings: Settings,
    probe: Callable[[str, str], bool] = ollama_has_model,
) -> Resolved:
    """Pick the answer mode. Explicit choices that cannot work refuse to start."""
    choice = settings.provider
    if choice == "claude":
        if not settings.anthropic_api_key:
            raise ConfigError(
                "ASK_HANA_PROVIDER=claude needs an API key. Set ANTHROPIC_API_KEY in .env, "
                "or use ASK_HANA_PROVIDER=extractive to run without a model."
            )
        return Resolved("claude", settings.claude_model, "ASK_HANA_PROVIDER is claude")
    if choice == "ollama":
        if not settings.ollama_model:
            raise ConfigError(
                "ASK_HANA_PROVIDER=ollama needs a model name. Set OLLAMA_MODEL in .env "
                '(for example "qwen3.5:9b") and pull it with "ollama pull <model>".'
            )
        return Resolved("ollama", settings.ollama_model, "ASK_HANA_PROVIDER is ollama")
    if choice == "extractive":
        return Resolved("extractive", None, "ASK_HANA_PROVIDER is extractive")

    if settings.anthropic_api_key:
        return Resolved("claude", settings.claude_model, "ANTHROPIC_API_KEY is set")
    if settings.ollama_model:
        if probe(settings.ollama_url, settings.ollama_model):
            return Resolved(
                "ollama", settings.ollama_model, f"{settings.ollama_model} is installed in Ollama"
            )
        log.info(
            "Ollama at %s does not list %s", safe_url(settings.ollama_url), settings.ollama_model
        )
        return Resolved(
            "extractive",
            None,
            f"no API key, and the local Ollama server does not list {settings.ollama_model}",
        )
    return Resolved("extractive", None, "no API key and no OLLAMA_MODEL set")
