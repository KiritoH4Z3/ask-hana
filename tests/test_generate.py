# Silent failures this file catches:
# - the Claude request losing its model, effort, fallback beta or delimiters (the answer still
#   looks fine, but safety fallbacks or prompt separation are gone)
# - a refusal read as an empty or normal answer
# - an SDK error class mapped to the wrong code (a bad key shown as "try again later")
# - the extractive mode inventing text, citing the wrong passage or varying between runs
from __future__ import annotations

import re

import anthropic
import httpx
import pytest

from ask_hana.errors import ProviderError
from ask_hana.generate import (
    FALLBACK_BETA,
    ClaudeGenerator,
    ExtractiveGenerator,
    OllamaGenerator,
    content_words,
)
from ask_hana.prompts import SYSTEM_PROMPT

from .conftest import make_hit

REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class FakeMessage:
    def __init__(self, text="Hana dives to 32 metres [1].", stop_reason="end_turn", content=None):
        self.stop_reason = stop_reason
        self.content = content if content is not None else [Block("text", text)]


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result, self._error = result, error
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result or FakeMessage()


def claude(client, **kw):
    return ClaudeGenerator("k", client=client, timeout_s=30, **kw)


def status_error(cls, code):
    return cls(
        "raw provider text SECRET-123", response=httpx.Response(code, request=REQ), body=None
    )


# ------------------------------------------------------------------ Claude


def test_claude_request_carries_everything_the_contract_requires():
    client = FakeClient()
    answer = claude(client, effort="medium").generate("How deep?", [make_hit(1), make_hit(2)])
    assert answer == "Hana dives to 32 metres [1]."
    (call,) = client.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "medium"}
    assert call["betas"] == [FALLBACK_BETA] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["max_tokens"] == 4096
    assert call["system"] == SYSTEM_PROMPT
    assert "thinking" not in call and "temperature" not in call
    (message,) = call["messages"]
    assert message["role"] == "user"
    body = message["content"]
    assert "<question>\nHow deep?\n</question>" in body
    assert body.count("<document n=") == 2 and "<documents>" in body


def test_claude_default_effort_is_low_and_model_is_overridable():
    client = FakeClient()
    ClaudeGenerator("k", model="claude-sonnet-5-5", client=client).generate("q", [make_hit()])
    assert client.calls[0]["output_config"] == {"effort": "low"}
    assert client.calls[0]["model"] == "claude-sonnet-5-5"


def test_claude_refusal_is_checked_before_content():
    client = FakeClient(result=FakeMessage(text="partial text", stop_reason="refusal"))
    with pytest.raises(ProviderError) as err:
        claude(client).generate("q", [make_hit()])
    assert err.value.code == "provider_refused" and err.value.status == 502


def test_claude_skips_thinking_blocks_and_joins_text():
    msg = FakeMessage(
        content=[
            Block("thinking", "secret chain"),
            Block("text", "A [1]."),
            Block("text", " B [2]."),
        ]
    )
    # Two different sources, so repeated-citation collapsing leaves both markers in place.
    passages = [make_hit(1), make_hit(2)]
    assert claude(FakeClient(result=msg)).generate("q", passages) == "A [1]. B [2]."


def test_claude_drops_citations_to_passages_it_was_not_given():
    msg = FakeMessage(text="True [1]. Invented [5].")
    assert claude(FakeClient(result=msg)).generate("q", [make_hit(1)]) == "True [1]. Invented."


def test_claude_empty_answer_is_not_a_provider_error():
    with pytest.raises(RuntimeError):
        claude(FakeClient(result=FakeMessage(content=[Block("thinking", "x")]))).generate(
            "q", [make_hit()]
        )


@pytest.mark.parametrize(
    ("error", "code", "status"),
    [
        (status_error(anthropic.AuthenticationError, 401), "provider_auth", 502),
        (status_error(anthropic.PermissionDeniedError, 403), "provider_auth", 502),
        (status_error(anthropic.NotFoundError, 404), "provider_model_missing", 502),
        (status_error(anthropic.RateLimitError, 429), "provider_rate_limited", 503),
        (status_error(anthropic.InternalServerError, 500), "provider_unavailable", 503),
        (status_error(anthropic.OverloadedError, 529), "provider_unavailable", 503),
        (status_error(anthropic.ServiceUnavailableError, 503), "provider_unavailable", 503),
        (status_error(anthropic.GatewayTimeoutError, 504), "provider_timeout", 504),
        (anthropic.APITimeoutError(request=REQ), "provider_timeout", 504),
        (anthropic.APIConnectionError(request=REQ), "provider_unavailable", 503),
    ],
)
def test_each_anthropic_error_maps_to_its_code(error, code, status):
    with pytest.raises(ProviderError) as err:
        claude(FakeClient(error=error)).generate("q", [make_hit()])
    assert (err.value.code, err.value.status) == (code, status)
    assert "SECRET-123" not in err.value.message
    assert err.value.__cause__ is None


def test_billing_status_gets_its_own_message():
    with pytest.raises(ProviderError) as err:
        claude(FakeClient(error=status_error(anthropic.APIStatusError, 402))).generate(
            "q", [make_hit()]
        )
    assert err.value.code == "provider_unavailable"
    assert "billing" in err.value.hint and "billing" not in err.value.message.lower()


def test_unmapped_client_errors_propagate_for_the_app_to_report_as_internal():
    with pytest.raises(anthropic.BadRequestError):
        claude(FakeClient(error=status_error(anthropic.BadRequestError, 400))).generate(
            "q", [make_hit()]
        )


def test_visitor_message_and_operator_hint_are_separate():
    """Env var names, commands and URLs go to the log hint, never to the visitor message."""
    msgs = {}
    for cls, code in [(anthropic.AuthenticationError, 401), (anthropic.NotFoundError, 404)]:
        with pytest.raises(ProviderError) as err:
            claude(FakeClient(error=status_error(cls, code))).generate("q", [make_hit()])
        msgs[err.value.code] = err.value
    assert "ANTHROPIC_API_KEY" in msgs["provider_auth"].hint
    assert "CLAUDE_MODEL" in msgs["provider_model_missing"].hint
    assert "claude-opus-5-5" in msgs["provider_model_missing"].hint
    for err in msgs.values():
        for leak in ("ANTHROPIC", "CLAUDE_MODEL", ".env", "claude-opus", "restart"):
            assert leak not in err.message


# ------------------------------------------------------------------ Ollama


def ollama(handler, **kw):
    return OllamaGenerator(
        "http://127.0.0.1:11434",
        "qwen3.5:9b",
        timeout_s=7,
        transport=httpx.MockTransport(handler),
        **kw,
    )


def test_ollama_request_shape_and_answer():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "  Hana swims [1].  "}}
        )

    answer = ollama(handler).generate("Does she swim?", [make_hit()])
    assert answer == "Hana swims [1]."
    body = seen["json"]
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert body["model"] == "qwen3.5:9b" and body["stream"] is False and body["think"] is False
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"temperature": 0.2, "num_predict": 400, "num_ctx": 8192}
    system, user = body["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    assert user["role"] == "user" and "<question>\nDoes she swim?\n</question>" in user["content"]


def test_ollama_strips_think_blocks():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "<think>hmm</think>Answer [1]."}})

    assert ollama(handler).generate("q", [make_hit()]) == "Answer [1]."


def test_ollama_connection_refused_tells_owner_to_serve():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError) as err:
        ollama(handler).generate("q", [make_hit()])
    assert (err.value.code, err.value.status) == ("provider_unavailable", 503)
    assert "ollama serve" in err.value.hint and "127.0.0.1:11434" in err.value.hint
    for leak in ("ollama", "127.0.0.1", "11434"):
        assert leak not in err.value.message.lower()
    assert "try again" in err.value.message.lower()


def test_ollama_missing_model_tells_owner_to_pull():
    def handler(request):
        return httpx.Response(404, json={"error": "model 'qwen3.5:9b' not found"})

    with pytest.raises(ProviderError) as err:
        ollama(handler).generate("q", [make_hit()])
    assert (err.value.code, err.value.status) == ("provider_model_missing", 502)
    assert "ollama pull qwen3.5:9b" in err.value.hint
    assert "qwen" not in err.value.message and "ollama" not in err.value.message.lower()


def test_ollama_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderError) as err:
        ollama(handler).generate("q", [make_hit()])
    assert (err.value.code, err.value.status) == ("provider_timeout", 504)
    assert "7 seconds" in err.value.hint and "PROVIDER_TIMEOUT_S" in err.value.hint
    assert "PROVIDER_TIMEOUT_S" not in err.value.message and "7 seconds" not in err.value.message


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(500, text="boom SECRET-123"), "provider_unavailable"),
        (httpx.Response(429, text="slow down"), "provider_rate_limited"),
        (httpx.Response(200, text="not json SECRET-123"), "provider_unavailable"),
        (httpx.Response(200, json={"unexpected": True}), "provider_unavailable"),
        (httpx.Response(200, json={"message": {"content": "   "}}), "provider_unavailable"),
    ],
)
def test_ollama_odd_replies_never_leak_raw_text(response, code):
    with pytest.raises(ProviderError) as err:
        ollama(lambda request: response).generate("q", [make_hit()])
    assert err.value.code == code and "SECRET-123" not in err.value.message


# ------------------------------------------------------------------ Extractive

DIVING = make_hit(
    1,
    text="Hana free dives on weekends. Her personal best is 32 metres in constant weight. "
    "She trains with a buddy and never dives alone.",
)
BAKING = make_hit(
    2, section="Baking", text="Hana bakes sourdough on Sundays. The starter is called Gustav."
)


def test_extractive_picks_the_best_sentence_and_cites_its_source():
    answer = ExtractiveGenerator().generate("What is her personal best dive?", [DIVING, BAKING])
    assert answer == "From Hana's pages: Her personal best is 32 metres in constant weight. [1]"


def test_extractive_cites_the_right_passage_number():
    answer = ExtractiveGenerator().generate("What is the starter called?", [DIVING, BAKING])
    assert answer == "From Hana's pages: The starter is called Gustav. [2]"


def test_extractive_keeps_source_order_and_caps_at_three():
    passages = [
        make_hit(1, text="Hana loves pottery wheels. Pottery wheels spin fast."),
        make_hit(
            2,
            text="Pottery wheels need water. Pottery wheels are heavy. Pottery wheels cost money.",
        ),
    ]
    answer = ExtractiveGenerator().generate("Tell me about pottery wheels", passages)
    assert answer.count("[") <= 3
    numbers = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    assert numbers == sorted(numbers) and answer.startswith("From Hana's pages: ")


def test_extractive_is_deterministic():
    gen = ExtractiveGenerator()
    first = gen.generate("Where does she dive on weekends?", [DIVING, BAKING])
    assert all(
        gen.generate("Where does she dive on weekends?", [DIVING, BAKING]) == first
        for _ in range(5)
    )


def test_extractive_with_no_overlap_falls_back_to_the_lead_sentence():
    answer = ExtractiveGenerator().generate("zzz qqq", [BAKING, DIVING])
    assert answer == "From Hana's pages: Hana bakes sourdough on Sundays. [2]"


def test_extractive_without_passages_is_empty_not_invented():
    assert ExtractiveGenerator().generate("anything", []) == ""


def test_content_words_drop_stopwords_and_plurals():
    assert content_words("What are the dives Hana does?") == {"dive"}
    assert ExtractiveGenerator.model is None and ExtractiveGenerator.mode == "extractive"


FAQ = make_hit(
    1,
    doc="faq.md",
    text="Who are you? Hana Idris, a hydrographic surveyor. Where do you live? In Fujairah, "
    "on the UAE east coast. What is your studio called? Datum Line Surveys, founded in 2021.",
)


def test_extractive_never_returns_a_faq_question_line_but_its_answer():
    """Silent failure: the FAQ 'Q? A.' line shares the most words with the visitor's question,
    so the question sentence won and the visitor got 'Where do you live? [1]' as an answer."""
    gen = ExtractiveGenerator()
    live = gen.generate("Where does Hana live?", [FAQ])
    assert "Fujairah" in live and "?" not in live
    who = gen.generate("Who is Hana?", [FAQ])
    assert "hydrographic surveyor" in who and "?" not in who
    studio = gen.generate("What is the studio called?", [FAQ])
    assert "Datum Line Surveys" in studio and "?" not in studio


def test_extractive_drops_a_trailing_question_with_no_answer_after_it():
    only_q = make_hit(1, text="Where do you live?")
    assert ExtractiveGenerator().generate("Where does she live?", [only_q]) == ""


def test_extractive_answers_open_with_a_quote_prefix():
    """Silent failure: first-person page text shown as if the assistant said it."""
    answer = ExtractiveGenerator().generate("What is her personal best dive?", [DIVING])
    assert answer.startswith("From Hana's pages: ")


def test_extractive_repeats_no_citation_for_one_source():
    answer = ExtractiveGenerator().generate(
        "Tell me about pottery wheels",
        [
            make_hit(
                1,
                text="Pottery wheels spin fast. Pottery wheels need water. "
                "Pottery wheels are heavy.",
            )
        ],
    )
    assert answer.count("[1]") == 1 and answer.endswith("[1]")
