"""FastAPI app: JSON API plus the static chat page."""

from __future__ import annotations

import json
import logging
import secrets
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError
from starlette.concurrency import run_in_threadpool

from . import errors as E
from .config import Resolved, Settings, load_settings, resolve_provider
from .errors import ConfigError, ProviderError
from .generate import ClaudeGenerator, ExtractiveGenerator, Generator, OllamaGenerator
from .prompts import NOT_FOUND_ANSWER
from .ratelimit import RateLimiter
from .store import EMBEDDING_MODEL, Hit, VectorStore

log = logging.getLogger("ask_hana.app")

MAX_BODY_BYTES = 4096
MAX_QUESTION_CHARS = 500
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[2] / "web"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class Retriever(Protocol):
    def query(self, question: str, k: int) -> list[Hit]: ...
    def list_documents(self) -> list[dict]: ...
    def stats(self) -> dict: ...


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: StrictStr


def _source(hit: Hit, used: bool) -> dict[str, Any]:
    return {
        "n": hit.n,
        "id": hit.id,
        "doc": hit.doc,
        "title": hit.title,
        "section": hit.section,
        "score": hit.score,
        "used": used,
        "text": hit.text,
    }


def _error(
    status: int,
    code: str,
    message: str,
    *,
    field: str | None = None,
    error_id: str | None = None,
    sources: Sequence[dict] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {"code": code, "message": message, "field": field, "error_id": error_id},
        "sources": list(sources),
    }
    return JSONResponse(body, status_code=status, headers=headers)


def _invalid(message: str, field: str | None = "question") -> JSONResponse:
    return _error(422, "invalid_question", message, field=field)


def _validation_message(exc: ValidationError) -> tuple[str, str | None]:
    """Field-level copy from pydantic's error types, never its raw text."""
    err = exc.errors()[0]
    loc = str(err["loc"][0]) if err["loc"] else None
    kind = err["type"]
    if kind == "extra_forbidden":
        return f'Unknown field "{loc}". Send only "question".', loc
    if kind == "missing":
        return 'Add a "question" field, like {"question": "What does Hana do?"}.', "question"
    if kind == "string_type":
        return "The question must be text. Send it as a JSON string.", "question"
    return 'Send a JSON object like {"question": "What does Hana do?"}.', None


async def _read_body(request: Request) -> bytes | None:
    """Read at most MAX_BODY_BYTES. None means the body was too large."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(part)
    return b"".join(chunks)


def build_generator(settings: Settings, resolved: Resolved) -> Generator:
    if resolved.mode == "claude":
        assert settings.anthropic_api_key  # resolve_provider already refused otherwise
        return ClaudeGenerator(
            settings.anthropic_api_key,
            model=settings.claude_model,
            effort=settings.claude_effort,
            timeout_s=settings.provider_timeout_s,
        )
    if resolved.mode == "ollama":
        assert settings.ollama_model
        return OllamaGenerator(
            settings.ollama_url, settings.ollama_model, timeout_s=settings.provider_timeout_s
        )
    return ExtractiveGenerator()


def create_app(
    settings: Settings | None = None,
    retriever: Retriever | None = None,
    generator: Generator | None = None,
    web_dir: Path | None = None,
    mode_reason: str | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    if generator is None:
        resolved = resolve_provider(settings)
        generator = build_generator(settings, resolved)
        mode_reason = resolved.reason
    mode_reason = mode_reason or "provided by the caller"
    log.info("Answer mode: %s (%s)", generator.mode, mode_reason)

    if retriever is None:
        store = VectorStore(settings.chroma_path, settings.knowledge_dir)
        report = store.ensure_index()
        log.info(
            "Index ready: %d documents, %d chunks (%s)",
            report.documents,
            report.chunks,
            "rebuilt" if report.rebuilt else "unchanged",
        )
        retriever = store

    limiter = RateLimiter(settings.rate_limit_per_minute)
    app = FastAPI(title="ask-hana", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    def done(status: str, started: float, q_len: int, **fields: Any) -> None:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        log.info(
            "chat status=%s mode=%s q_len=%d total_ms=%d %s",
            status,
            generator.mode,
            q_len,
            (time.perf_counter() - started) * 1000,
            extra,
        )

    @app.post("/api/chat")
    async def chat(request: Request):
        started = time.perf_counter()
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = limiter.check(client)
        if not allowed:
            done("429", started, 0, code="rate_limited")
            return _error(
                429,
                "rate_limited",
                f"Too many questions in a short time. Wait {retry_after} seconds and ask again.",
                headers={"Retry-After": str(retry_after)},
            )

        raw = await _read_body(request)
        if raw is None:
            done("413", started, 0, code="payload_too_large")
            return _error(
                413,
                "payload_too_large",
                f"That request is larger than {MAX_BODY_BYTES} bytes. Send just the question.",
            )
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            done("422", started, len(raw), code="invalid_question")
            return _invalid('Send a JSON object like {"question": "What does Hana do?"}.', None)
        try:
            body = ChatBody.model_validate(payload)
        except ValidationError as exc:
            message, field = _validation_message(exc)
            done("422", started, 0, code="invalid_question")
            return _invalid(message, field)

        question = body.question.strip()
        if not question:
            done("422", started, 0, code="invalid_question")
            return _invalid("Type a question first. It needs at least one character.")
        try:
            question.encode("utf-8")
        except UnicodeEncodeError:
            done("422", started, len(question), code="invalid_question")
            return _invalid("The question contains characters that are not valid text. Retype it.")
        if len(question) > MAX_QUESTION_CHARS:
            done("422", started, len(question), code="invalid_question")
            return _invalid(
                f"Keep the question to {MAX_QUESTION_CHARS} characters or fewer "
                f"(this one is {len(question)})."
            )

        hits: list[Hit] = []
        try:
            t0 = time.perf_counter()
            hits = await run_in_threadpool(retriever.query, question, settings.top_k)
            retrieve_ms = round((time.perf_counter() - t0) * 1000)

            grounded = bool(hits) and max(h.score for h in hits) >= settings.min_score
            used_ids = {h.id for h in hits if h.score >= settings.min_score} if grounded else set()
            generate_ms = 0
            if grounded:
                t1 = time.perf_counter()
                answer = await run_in_threadpool(
                    generator.generate, question, [h for h in hits if h.id in used_ids]
                )
                generate_ms = round((time.perf_counter() - t1) * 1000)
            else:
                answer = NOT_FOUND_ANSWER
        except ProviderError as exc:
            sources = [_source(h, h.score >= settings.min_score) for h in hits]
            error_id = secrets.token_hex(6)
            # The operator hint (env var, command, URL) stays here; the visitor gets exc.message.
            log.warning(
                "chat provider error error_id=%s code=%s hint=%s", error_id, exc.code, exc.hint
            )
            done(str(exc.status), started, len(question), code=exc.code, error_id=error_id)
            return _error(exc.status, exc.code, exc.message, error_id=error_id, sources=sources)
        except Exception as exc:
            error_id = secrets.token_hex(6)
            frames = "".join(traceback.format_tb(exc.__traceback__)).strip().replace("\n", " | ")
            log.error(
                "chat internal error_id=%s type=%s at %s", error_id, type(exc).__name__, frames
            )
            done("500", started, len(question), code="internal", error_id=error_id)
            return _error(
                500,
                "internal",
                E.internal_message(error_id),
                error_id=error_id,
                sources=[_source(h, h.score >= settings.min_score) for h in hits],
            )

        total_ms = round((time.perf_counter() - started) * 1000)
        done(
            "200",
            started,
            len(question),
            grounded=grounded,
            retrieve_ms=retrieve_ms,
            generate_ms=generate_ms,
        )
        return {
            "answer": answer,
            "mode": generator.mode,
            "model": generator.model,
            "grounded": grounded,
            "threshold": settings.min_score,
            "sources": [_source(h, h.id in used_ids) for h in hits],
            "timing": {
                "retrieve_ms": retrieve_ms,
                "generate_ms": generate_ms,
                "total_ms": total_ms,
            },
        }

    @app.api_route("/api/health", methods=["GET", "HEAD"])
    def health():
        stats = retriever.stats()
        return {
            "status": "ok",
            "mode": generator.mode,
            "model": generator.model,
            "mode_reason": mode_reason,
            "documents": stats.get("documents", 0),
            "chunks": stats.get("chunks", 0),
            "embedding_model": stats.get("embedding_model", EMBEDDING_MODEL),
            "threshold": settings.min_score,
            "top_k": settings.top_k,
        }

    @app.get("/api/documents")
    def documents():
        return {"documents": retriever.list_documents()}

    site = web_dir or DEFAULT_WEB_DIR
    if site.is_dir():
        app.mount("/", StaticFiles(directory=site, html=True), name="web")
    else:
        log.warning("Web directory %s not found; serving the API only", site)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        settings = load_settings()
        app = create_app(settings)
    except ConfigError as exc:
        print(f"ask-hana cannot start: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False, log_level="info")
