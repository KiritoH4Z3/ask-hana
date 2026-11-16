"""Three answer generators behind one interface.

Provider failures are mapped to typed `ProviderError`s with fixed, actionable copy.
Raw SDK and HTTP error text is never read into a message.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Protocol

import anthropic
import httpx

from . import errors as E
from .errors import ProviderError
from .prompts import (
    SYSTEM_PROMPT,
    build_user_message,
    collapse_repeated_citations,
    sanitize_citations,
    tidy_spacing,
)
from .store import Hit

log = logging.getLogger("ask_hana.generate")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Generator(Protocol):
    mode: str
    model: str | None

    def generate(self, question: str, passages: Sequence[Hit]) -> str: ...


# --------------------------------------------------------------------------- Claude


class ClaudeGenerator:
    mode = "claude"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-5-5",
        effort: str = "low",
        timeout_s: float = 60.0,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self._effort = effort
        self._timeout_s = timeout_s
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_s, max_retries=1
        )

    def _timeout(self) -> ProviderError:
        return ProviderError(
            "provider_timeout", E.timeout_message(), E.timeout_hint(self._timeout_s)
        )

    @staticmethod
    def _unavailable() -> ProviderError:
        return ProviderError(
            "provider_unavailable", E.service_unavailable_message(), E.claude_unavailable_hint()
        )

    def generate(self, question: str, passages: Sequence[Hit]) -> str:
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(question, passages)}],
                output_config={"effort": self._effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError:
            raise self._timeout() from None
        except anthropic.APIConnectionError:
            raise self._unavailable() from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise ProviderError(
                "provider_auth", E.service_not_ready_message(), E.claude_auth_hint()
            ) from None
        except anthropic.NotFoundError:
            raise ProviderError(
                "provider_model_missing",
                E.service_not_ready_message(),
                E.claude_model_missing_hint(self.model),
            ) from None
        except anthropic.RateLimitError:
            raise ProviderError(
                "provider_rate_limited",
                E.rate_limited_upstream_message(),
                E.rate_limited_upstream_hint("Anthropic"),
            ) from None
        except (anthropic.GatewayTimeoutError, anthropic.RequestTimeoutError):
            raise self._timeout() from None
        except anthropic.InternalServerError:  # includes overloaded and service unavailable
            raise self._unavailable() from None
        except anthropic.APIStatusError as exc:
            if exc.status_code == 402:
                raise ProviderError(
                    "provider_unavailable",
                    E.service_unavailable_message(),
                    E.claude_billing_hint(),
                ) from None
            raise  # a 400 or similar means our request is wrong: the app reports it as internal

        if response.stop_reason == "refusal":
            raise ProviderError("provider_refused", E.refused_message(), E.refused_hint())

        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if not text:
            raise RuntimeError(f"empty Claude answer (stop_reason={response.stop_reason})")
        return sanitize_citations(text, [p.n for p in passages])


# --------------------------------------------------------------------------- Ollama

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaGenerator:
    mode = "ollama"

    def __init__(
        self,
        url: str,
        model: str,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._url = url.rstrip("/")
        self._timeout_s = timeout_s
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def _unreachable(self) -> ProviderError:
        return ProviderError(
            "provider_unavailable",
            E.service_unavailable_message(),
            E.ollama_unreachable_hint(self._url),
        )

    def generate(self, question: str, passages: Sequence[Hit]) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 400, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(question, passages)},
            ],
        }
        try:
            reply = self._http.post(f"{self._url}/api/chat", json=body)
        except httpx.TimeoutException:
            raise ProviderError(
                "provider_timeout", E.timeout_message(), E.timeout_hint(self._timeout_s)
            ) from None
        except httpx.TransportError:
            raise self._unreachable() from None

        if reply.status_code == 404:
            raise ProviderError(
                "provider_model_missing",
                E.service_not_ready_message(),
                E.ollama_model_missing_hint(self.model),
            )
        if reply.status_code == 429:
            raise ProviderError(
                "provider_rate_limited",
                E.rate_limited_upstream_message(),
                E.rate_limited_upstream_hint("Ollama"),
            )
        if reply.status_code != 200:
            raise self._unreachable()
        try:
            text = reply.json()["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise ProviderError(
                "provider_unavailable", E.bad_reply_message(), E.ollama_bad_reply_hint()
            ) from None
        text = _THINK.sub("", text).strip()
        if not text:
            raise ProviderError(
                "provider_unavailable", E.bad_reply_message(), E.ollama_empty_hint()
            )
        return sanitize_citations(text, [p.n for p in passages])


# --------------------------------------------------------------------------- Extractive

STOPWORDS = frozenset(
    """a about after all also am an and any are as at be been being but by can could did do does
    for from get got had has have he her hers hi him his how i if in into is it its just like me
    my no not of on or our out she so some tell than that the their them then there these they
    this those to too up us was we were what when where which who whom why will with would you
    your hana""".split()
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])|\n+")


def content_words(text: str) -> set[str]:
    words = set()
    for token in _TOKEN.findall(text.lower()):
        if token in STOPWORDS or len(token) < 2:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        words.add(token)
    return words


EXTRACTIVE_PREFIX = "From Hana's pages: "


class ExtractiveGenerator:
    """No model: quote the sentences that share the most content words with the question.

    The pages are written in the first person, so the answer opens with a prefix that marks it
    as a quote. A sentence ending in "?" is a question line from the FAQ: it is never quoted on
    its own, but its words count toward the answer sentence that follows it.
    """

    mode = "extractive"
    model: str | None = None

    def generate(self, question: str, passages: Sequence[Hit]) -> str:
        wanted = content_words(question)
        candidates: list[tuple[int, int, int, str, int]] = []  # score, source idx, pos, text, n
        for idx, passage in enumerate(passages):
            carried: set[str] = set()  # words of the question line(s) just before a sentence
            for pos, sentence in enumerate(s.strip() for s in _SPLIT.split(passage.text)):
                if not sentence:
                    continue
                if sentence.endswith("?"):
                    carried |= content_words(sentence)
                    continue
                score = len(wanted & (content_words(sentence) | carried))
                carried = set()
                candidates.append((score, idx, pos, sentence, passage.n))
        if not candidates:
            return ""
        best = max(c[0] for c in candidates)
        if best == 0:
            chosen = [min(candidates, key=lambda c: (c[1], c[2]))]
        else:
            ranked = sorted(
                (c for c in candidates if c[0] * 4 >= best * 3), key=lambda c: (-c[0], c[1], c[2])
            )
            chosen = ranked[:3]
        chosen.sort(key=lambda c: (c[1], c[2]))
        quoted = " ".join(f"{s.rstrip()} [{n}]" for _, _, _, s, n in chosen)
        return EXTRACTIVE_PREFIX + tidy_spacing(collapse_repeated_citations(quoted))
