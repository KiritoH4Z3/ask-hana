# Silent failures this file catches:
# - the response shape drifting from what web/app.js reads (the page would render nothing, no error)
# - an off-topic question reaching a paid model (grounded=false must short-circuit)
# - raw pydantic, provider or Python exception text reaching a visitor
# - a security header missing on one response class (static page, API, error)
# - the question text appearing in logs (public visitors type personal things)
# - a provider failure hiding the passages that were found
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ask_hana.app import SECURITY_HEADERS, create_app
from ask_hana.config import Settings
from ask_hana.errors import ProviderError
from ask_hana.generate import ExtractiveGenerator, OllamaGenerator

from .conftest import make_hit

HITS = [
    make_hit(1, 0.712, "Her personal best is 32 metres in constant weight."),
    make_hit(2, 0.41, "She trains with a buddy.", section="Safety", id="id00000000000002"),
    make_hit(3, 0.22, "Gustav is a sourdough starter.", section="Baking", id="id00000000000003"),
]
FAR = [make_hit(1, 0.12), make_hit(2, 0.09, id="id00000000000002")]


class FakeRetriever:
    def __init__(self, hits=HITS):
        self.hits, self.calls = hits, []

    def query(self, question, k):
        self.calls.append((question, k))
        return list(self.hits)[:k]

    def list_documents(self):
        return [
            {
                "doc": "hobbies.md",
                "title": "Hobbies",
                "sections": ["Free diving"],
                "chunks": 1,
                "words": 9,
            }
        ]

    def stats(self):
        return {"documents": 1, "chunks": 3, "embedding_model": "all-MiniLM-L6-v2"}


class FakeGenerator:
    mode, model = "claude", "claude-opus-5-5"

    def __init__(self, answer="She dives to 32 metres [1].", error=None):
        self.answer, self.error, self.calls = answer, error, []

    def generate(self, question, passages):
        self.calls.append((question, [p.n for p in passages]))
        if self.error:
            raise self.error
        return self.answer


def client_for(retriever=None, generator=None, **settings_kw):
    base = {"min_score": 0.30, "top_k": 4, "rate_limit_per_minute": 100} | settings_kw
    settings = Settings(**base)
    app = create_app(
        settings, retriever or FakeRetriever(), generator or FakeGenerator(), web_dir=None
    )
    return TestClient(app)


def post(c, body, headers=None):
    headers = {"content-type": "application/json"} | (headers or {})
    return c.post("/api/chat", content=json.dumps(body), headers=headers)


def assert_error(r, status, code, field=None):
    assert r.status_code == status
    body = r.json()
    assert set(body) == {"error", "sources"}
    assert set(body["error"]) == {"code", "message", "field", "error_id"}
    assert body["error"]["code"] == code and body["error"]["field"] == field
    assert body["error"]["message"] and "pydantic" not in r.text.lower()
    return body


# ---------------------------------------------------------------- 200


def test_grounded_answer_has_exactly_the_contract_shape():
    gen = FakeGenerator()
    r = post(client_for(generator=gen), {"question": "  How deep can Hana dive?  "})
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["answer", "mode", "model", "grounded", "threshold", "sources", "timing"]
    assert body["answer"] == "She dives to 32 metres [1]."
    assert (body["mode"], body["model"], body["grounded"], body["threshold"]) == (
        "claude",
        "claude-opus-5-5",
        True,
        0.3,
    )
    assert [s["n"] for s in body["sources"]] == [1, 2, 3]
    assert list(body["sources"][0]) == [
        "n",
        "id",
        "doc",
        "title",
        "section",
        "score",
        "used",
        "text",
    ]
    assert [s["used"] for s in body["sources"]] == [True, True, False]
    assert [s["score"] for s in body["sources"]] == [0.712, 0.41, 0.22]
    assert list(body["timing"]) == ["retrieve_ms", "generate_ms", "total_ms"]
    assert all(isinstance(v, int) for v in body["timing"].values())
    assert gen.calls == [("How deep can Hana dive?", [1, 2])]  # trimmed, and only used passages


def test_top_k_comes_from_settings():
    retriever = FakeRetriever()
    client_for(retriever, top_k=2).post("/api/chat", json={"question": "hi"})
    assert retriever.calls == [("hi", 2)]


def test_ungrounded_short_circuits_without_calling_the_generator():
    gen = FakeGenerator()
    r = post(client_for(FakeRetriever(FAR), gen), {"question": "What is the capital of France?"})
    body = r.json()
    assert r.status_code == 200 and gen.calls == []
    assert body["grounded"] is False
    assert body["answer"].startswith("I could not find that")
    assert [s["used"] for s in body["sources"]] == [False, False]
    assert body["timing"]["generate_ms"] == 0


def test_empty_index_is_ungrounded_not_an_error():
    r = post(client_for(FakeRetriever([]), FakeGenerator()), {"question": "anything"})
    assert r.status_code == 200 and r.json()["grounded"] is False and r.json()["sources"] == []


def test_extractive_mode_end_to_end_with_null_model():
    c = client_for(generator=ExtractiveGenerator())
    body = post(c, {"question": "What is her personal best?"}).json()
    assert (body["mode"], body["model"]) == ("extractive", None)
    assert (
        body["answer"]
        == "From Hana's pages: Her personal best is 32 metres in constant weight. [1]"
    )


# ---------------------------------------------------------------- 422 and 413


@pytest.mark.parametrize(
    ("body", "field", "needle"),
    [
        ({"question": ""}, "question", "at least one character"),
        ({"question": "   "}, "question", "at least one character"),
        ({"question": "x" * 501}, "question", "500 characters"),
        ({"question": "hi", "extra": 1}, "extra", 'Unknown field "extra"'),
        ({"question": 42}, "question", "must be text"),
        ({"question": None}, "question", "must be text"),
        ({}, "question", "Add a"),
        (["question"], None, "JSON object"),
    ],
)
def test_validation_gives_field_level_messages_without_internals(body, field, needle):
    gen = FakeGenerator()
    r = post(client_for(generator=gen), body)
    out = assert_error(r, 422, "invalid_question", field)
    assert needle in out["error"]["message"]
    for leak in ("loc", "ctx", "input", "type=", "validation error", "pydantic"):
        assert leak not in r.text.lower().replace("invalid_question", "")
    assert gen.calls == []


def test_500_character_question_is_accepted():
    assert post(client_for(), {"question": "x" * 500}).status_code == 200


def test_malformed_json_is_422():
    r = client_for().post(
        "/api/chat", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert_error(r, 422, "invalid_question")


def test_body_over_4kb_is_413_with_the_same_error_shape():
    r = post(client_for(), {"question": "x" * 5000})
    assert_error(r, 413, "payload_too_large")
    r = client_for().post("/api/chat", content=b"{" + b" " * 4200 + b"}")
    assert_error(r, 413, "payload_too_large")


# ---------------------------------------------------------------- 429


def test_rate_limit_returns_429_with_retry_after():
    c = client_for(rate_limit_per_minute=2)
    for _ in range(2):
        assert post(c, {"question": "hi"}).status_code == 200
    r = post(c, {"question": "hi"})
    body = assert_error(r, 429, "rate_limited")
    retry = int(r.headers["retry-after"])
    assert 1 <= retry <= 60 and str(retry) in body["error"]["message"]


def test_limit_does_not_apply_to_health_or_documents():
    c = client_for(rate_limit_per_minute=1)
    post(c, {"question": "hi"})
    assert all(
        c.get(p).status_code == 200 for p in ("/api/health", "/api/documents") for _ in range(3)
    )


def test_forwarded_for_is_not_trusted():
    c = client_for(rate_limit_per_minute=1)
    assert post(c, {"question": "a"}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    r = post(c, {"question": "a"}, headers={"x-forwarded-for": "2.2.2.2"})
    assert r.status_code == 429


# ---------------------------------------------------------------- provider errors


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("provider_auth", 502),
        ("provider_model_missing", 502),
        ("provider_unavailable", 503),
        ("provider_rate_limited", 503),
        ("provider_timeout", 504),
        ("provider_refused", 502),
    ],
)
def test_provider_errors_keep_status_code_and_sources_and_hide_raw_text(code, status):
    gen = FakeGenerator(error=ProviderError(code, "Fixed advice for the visitor."))
    r = post(client_for(generator=gen), {"question": "How deep?"})
    body = assert_error(r, status, code)
    assert body["error"]["message"] == "Fixed advice for the visitor."
    assert [s["n"] for s in body["sources"]] == [1, 2, 3]
    assert body["sources"][0]["text"] and body["sources"][0]["used"] is True


def test_unexpected_exception_is_500_with_error_id_and_no_raw_text(caplog):
    gen = FakeGenerator(error=RuntimeError("db password is hunter2"))
    with caplog.at_level(logging.INFO, logger="ask_hana"):
        r = post(client_for(generator=gen), {"question": "How deep?"})
    body = assert_error(r, 500, "internal")
    error_id = body["error"]["error_id"]
    assert len(error_id) == 12 and error_id in body["error"]["message"]
    assert "hunter2" not in r.text and "hunter2" not in caplog.text
    assert error_id in caplog.text and "RuntimeError" in caplog.text
    assert len(body["sources"]) == 3


def test_retriever_failure_is_internal_too():
    class Broken(FakeRetriever):
        def query(self, question, k):
            raise OSError("disk exploded")

    r = post(client_for(Broken()), {"question": "hi"})
    body = assert_error(r, 500, "internal")
    assert body["sources"] == [] and "disk" not in r.text


# ---------------------------------------------------------------- health, documents, headers


def test_health_shape():
    body = client_for().get("/api/health").json()
    assert body == {
        "status": "ok",
        "mode": "claude",
        "model": "claude-opus-5-5",
        "mode_reason": "provided by the caller",
        "documents": 1,
        "chunks": 3,
        "embedding_model": "all-MiniLM-L6-v2",
        "threshold": 0.3,
        "top_k": 4,
    }


def test_documents_shape():
    docs = client_for().get("/api/documents").json()["documents"]
    assert list(docs[0]) == ["doc", "title", "sections", "chunks", "words"]


def test_security_headers_on_api_errors_and_static(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    app = create_app(Settings(), FakeRetriever(), FakeGenerator(), web_dir=tmp_path)
    c = TestClient(app)
    responses = [
        c.get("/"),
        c.get("/index.html"),
        c.get("/api/health"),
        c.get("/api/documents"),
        post(c, {"question": "hi"}),
        post(c, {"question": ""}),
        c.get("/nope"),
        c.get("/api/nope"),
    ]
    assert responses[0].status_code == 200 and "<title>t</title>" in responses[0].text
    for r in responses:
        for name, value in SECURITY_HEADERS.items():
            assert r.headers.get(name) == value, (r.request.url, name)
    csp = responses[0].headers["content-security-policy"]
    assert "unsafe" not in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp


def test_api_routes_win_over_the_static_mount(tmp_path):
    (tmp_path / "index.html").write_text("page")
    app = create_app(Settings(), FakeRetriever(), FakeGenerator(), web_dir=tmp_path)
    assert TestClient(app).get("/api/health").json()["status"] == "ok"


def test_missing_web_dir_serves_the_api_only(tmp_path):
    c = TestClient(
        create_app(Settings(), FakeRetriever(), FakeGenerator(), web_dir=tmp_path / "none")
    )
    assert c.get("/api/health").status_code == 200 and c.get("/").status_code == 404


# ---------------------------------------------------------------- logging


def test_question_text_never_reaches_logs_but_its_length_does(caplog):
    secret = "my passport number is X1234567 and I live at 12 Palm Road"
    gens = [
        FakeGenerator(),
        FakeGenerator(error=ProviderError("provider_timeout", "slow")),
        FakeGenerator(error=RuntimeError(secret)),
    ]
    with caplog.at_level(logging.DEBUG):
        for gen in gens:
            post(client_for(generator=gen), {"question": secret})
        post(client_for(), {"question": secret + "x" * 500})
    assert "X1234567" not in caplog.text and "Palm Road" not in caplog.text
    assert f"q_len={len(secret)}" in caplog.text
    assert "status=200" in caplog.text and "code=provider_timeout" in caplog.text


def test_secret_key_never_logged(caplog):
    from ask_hana.app import build_generator
    from ask_hana.config import Resolved

    s = Settings(anthropic_api_key="sk-ant-supersecret")
    with caplog.at_level(logging.DEBUG):
        build_generator(s, Resolved("claude", s.claude_model, "test"))
        create_app(s, FakeRetriever(), FakeGenerator(), web_dir=None)
    assert "supersecret" not in caplog.text


# ---------------------------------------------------------------- review fixes


class SlowGenerator(FakeGenerator):
    def generate(self, question, passages):
        time.sleep(1.5)
        return super().generate(question, passages)


class SlowRetriever(FakeRetriever):
    def query(self, question, k):
        time.sleep(1.0)
        return super().query(question, k)


@pytest.mark.parametrize(
    ("retriever", "generator"),
    [(FakeRetriever(), SlowGenerator()), (SlowRetriever(), FakeGenerator())],
)
def test_a_slow_answer_does_not_block_the_rest_of_the_server(retriever, generator):
    """Silent failure: `async def chat` ran the blocking retriever and generator on the event
    loop, so one visitor waiting for a model stalled /api/health and every other request."""
    settings = Settings(min_score=0.30, top_k=4, rate_limit_per_minute=100)
    app = create_app(settings, retriever, generator, web_dir=None)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            started = time.perf_counter()
            slow = asyncio.create_task(c.post("/api/chat", json={"question": "How deep?"}))
            await asyncio.sleep(0.2)
            health = await c.get("/api/health")
            # Measured from before the chat began: a blocked loop delays the health reply
            # until the chat's work is done (1.0 s or more), a free loop answers in ~0.2 s.
            waited = time.perf_counter() - started
            assert (await slow).status_code == 200
            return health.status_code, waited

    status, waited = asyncio.run(scenario())
    assert status == 200 and waited < 0.8, waited


def test_health_answers_head_requests():
    """Silent failure: uptime checks use HEAD and got a 404 from a healthy server."""
    c = client_for()
    r = c.head("/api/health")
    assert r.status_code == 200 and r.content == b""
    assert c.get("/api/health").status_code == 200


def test_lone_surrogate_is_a_422_not_a_500(caplog):
    """Silent failure: a JSON lone surrogate passed validation and crashed the tokenizer."""
    c = client_for()
    r = c.post(
        "/api/chat",
        content=b'{"question": "\\ud800 where does Hana live"}',
        headers={"content-type": "application/json"},
    )
    body = assert_error(r, 422, "invalid_question", "question")
    assert "not valid text" in body["error"]["message"]


def test_provider_error_logs_the_operator_hint_but_never_returns_it(caplog):
    err = ProviderError("provider_unavailable", "Try again in a moment.", "Start ollama serve.")
    with caplog.at_level(logging.INFO, logger="ask_hana"):
        r = post(client_for(generator=FakeGenerator(error=err)), {"question": "How deep?"})
    body = assert_error(r, 503, "provider_unavailable")
    error_id = body["error"]["error_id"]
    assert len(error_id) == 12
    assert "ollama serve" not in r.text
    assert error_id in caplog.text and "ollama serve" in caplog.text


def test_a_configured_ollama_url_never_reaches_a_visitor(caplog):
    """Silent failure: the error copy echoed OLLAMA_URL, credentials included, to every visitor."""

    def refuse(request):
        raise httpx.ConnectError("refused")

    gen = OllamaGenerator(
        "https://demo:s3cret@ollama.internal.example:11434",
        "qwen3.5:9b",
        transport=httpx.MockTransport(refuse),
    )
    with caplog.at_level(logging.INFO, logger="ask_hana"):
        r = post(client_for(generator=gen), {"question": "How deep?"})
    assert r.status_code == 503
    for secret in ("s3cret", "demo", "internal.example", "11434", "qwen", "ollama"):
        assert secret not in r.text.lower(), secret
    assert "ollama.internal.example:11434" in caplog.text  # the operator still sees the host
    assert "s3cret" not in caplog.text
