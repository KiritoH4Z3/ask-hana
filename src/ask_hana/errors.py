"""Typed errors and the client-facing copy for each error code.

Two audiences, two texts. `message` goes to the visitor: what happened and what they can do,
with no env var, command, URL or account detail. `hint` is for the person running the app: it
goes to the server log next to the error id and never into a response. Raw exception text
reaches neither: both are built from fixed templates.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# code -> HTTP status, exactly the table in the build contract.
STATUS_BY_CODE: dict[str, int] = {
    "invalid_question": 422,
    "payload_too_large": 413,
    "rate_limited": 429,
    "provider_auth": 502,
    "provider_model_missing": 502,
    "provider_unavailable": 503,
    "provider_rate_limited": 503,
    "provider_timeout": 504,
    "provider_refused": 502,
    "internal": 500,
}

PROVIDER_CODES = frozenset(c for c in STATUS_BY_CODE if c.startswith("provider_"))


class ConfigError(Exception):
    """Startup configuration is unusable. The message tells the owner what to set."""


class ProviderError(Exception):
    """A model provider failed in a way we can explain to the visitor."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        if code not in PROVIDER_CODES:
            raise ValueError(f"not a provider error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    @property
    def status(self) -> int:
        return STATUS_BY_CODE[self.code]


def safe_url(url: str) -> str:
    """scheme://host:port only, so credentials and paths in a configured URL never get logged."""
    parts = urlsplit(url)
    host = parts.hostname or "unknown-host"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


# ---- visitor copy: one sentence of what happened, one of what to do ----------------------


def service_unavailable_message() -> str:
    return "The answering service is busy or offline right now. Try again in a moment."


def service_not_ready_message() -> str:
    return (
        "The answering service is not working right now, so there is no written answer. "
        "Try again later."
    )


def rate_limited_upstream_message() -> str:
    return "The answering service is receiving too many requests. Wait a minute and ask again."


def timeout_message() -> str:
    return "The answer took too long to write. Try a shorter question, or ask again in a moment."


def refused_message() -> str:
    return (
        "The assistant declined to answer this question. Rephrase it, or ask about something "
        "the documents cover."
    )


def bad_reply_message() -> str:
    return "The answering service sent back something unreadable. Ask again in a moment."


def internal_message(error_id: str) -> str:
    return f"Something went wrong on the server. If it keeps happening, quote error id {error_id}."


# ---- operator hints: server log only -------------------------------------------------------


def claude_auth_hint() -> str:
    return "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env, then restart."


def claude_model_missing_hint(model: str) -> str:
    return f"Anthropic does not know the model {model}. Check CLAUDE_MODEL in .env, then restart."


def claude_unavailable_hint() -> str:
    return "The Claude API is busy or unreachable. It usually clears within a minute."


def claude_billing_hint() -> str:
    return "Anthropic declined the request for a billing reason. Check the credit balance."


def rate_limited_upstream_hint(provider: str) -> str:
    return f"{provider} is rate limiting requests."


def timeout_hint(seconds: float) -> str:
    return f"No answer within {seconds:g} seconds. Raise PROVIDER_TIMEOUT_S if this is normal."


def refused_hint() -> str:
    return "Claude refused the request after fallbacks."


def ollama_unreachable_hint(url: str) -> str:
    return f'Ollama is not reachable at {safe_url(url)}. Start it with "ollama serve".'


def ollama_model_missing_hint(model: str) -> str:
    return f'Ollama does not have the model {model}. Run "ollama pull {model}".'


def ollama_bad_reply_hint() -> str:
    return "Ollama sent a reply this app could not read. Update Ollama, or change OLLAMA_MODEL."


def ollama_empty_hint() -> str:
    return "The local model returned an empty answer. Try a different OLLAMA_MODEL."
