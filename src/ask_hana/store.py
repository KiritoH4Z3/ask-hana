"""ChromaDB wrapper: build the index, skip rebuilds when nothing changed, query."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from .chunking import CHUNKER_VERSION, Chunk, knowledge_files, load_chunks

log = logging.getLogger("ask_hana.store")

COLLECTION = "hana_docs"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_BATCH = 64
_LATE_BUILD_INTERVAL_S = 5.0

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class Hit:
    n: int
    id: str
    doc: str
    title: str
    section: str
    position: int
    text: str
    score: float


@dataclass(frozen=True)
class IndexReport:
    rebuilt: bool
    documents: int
    chunks: int
    words: int
    seconds: float


def default_embedder() -> Embedder:
    """Chroma's bundled ONNX MiniLM. Created once per store, no torch involved."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    fn = DefaultEmbeddingFunction()

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in fn(list(texts))]

    return embed


def fingerprint(knowledge_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in knowledge_files(knowledge_dir):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(f"chunker={CHUNKER_VERSION};embedding={EMBEDDING_MODEL}".encode())
    return digest.hexdigest()


class VectorStore:
    def __init__(
        self, chroma_path: Path, knowledge_dir: Path, embedder: Embedder | None = None
    ) -> None:
        self.chroma_path = Path(chroma_path)
        self.knowledge_dir = Path(knowledge_dir)
        self._embed = embedder or default_embedder()
        self._lock = threading.RLock()
        self._last_late_check = 0.0
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    # -- index lifecycle -------------------------------------------------

    def _existing(self):
        try:
            return self._client.get_collection(COLLECTION)
        except Exception:  # chroma raises different types across versions when absent
            return None

    def ensure_index(self) -> IndexReport:
        """Rebuild only when the fingerprint changed or the collection is empty."""
        with self._lock:
            started = time.perf_counter()
            wanted = fingerprint(self.knowledge_dir)
            col = self._existing()
            if (
                col is not None
                and col.count() > 0
                and (col.metadata or {}).get("fingerprint") == wanted
            ):
                docs, words = self._totals(col)
                return IndexReport(False, docs, col.count(), words, time.perf_counter() - started)
            return self._build(wanted, started)

    def rebuild(self) -> IndexReport:
        with self._lock:
            return self._build(fingerprint(self.knowledge_dir), time.perf_counter())

    def _build(self, wanted: str, started: float) -> IndexReport:
        chunks = load_chunks(self.knowledge_dir)
        if self._existing() is not None:
            self._client.delete_collection(COLLECTION)
        col = self._client.create_collection(
            COLLECTION,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"fingerprint": wanted, "embedding_model": EMBEDDING_MODEL},
            embedding_function=None,
        )
        for i in range(0, len(chunks), _BATCH):
            batch = chunks[i : i + _BATCH]
            col.add(
                ids=[c.id for c in batch],
                embeddings=self._embed([c.embed_text for c in batch]),
                documents=[c.text for c in batch],
                metadatas=[_metadata(c) for c in batch],
            )
        if not chunks:
            log.warning(
                "No markdown documents found in %s. Add .md files there and restart, "
                "or run ask-hana-ingest.",
                self.knowledge_dir,
            )
        docs = len({c.doc for c in chunks})
        words = sum(c.words for c in chunks)
        log.info("Index built: %d documents, %d chunks", docs, len(chunks))
        return IndexReport(True, docs, len(chunks), words, time.perf_counter() - started)

    def _late_build(self) -> None:
        """If the index is empty and documents have appeared since startup, build it once."""
        now = time.monotonic()
        if now - self._last_late_check < _LATE_BUILD_INTERVAL_S:
            return
        self._last_late_check = now
        if knowledge_files(self.knowledge_dir):
            log.info("Documents appeared in %s; building the index", self.knowledge_dir)
            self.ensure_index()

    # -- reads -------------------------------------------------------------

    def query(self, question: str, k: int) -> list[Hit]:
        with self._lock:
            col = self._existing()
            if col is None or col.count() == 0:
                self._late_build()
                col = self._existing()
            if col is None or col.count() == 0:
                return []
            result = col.query(
                query_embeddings=self._embed([question]),
                n_results=min(k, col.count()),
                include=["documents", "metadatas", "distances"],
            )
        hits: list[Hit] = []
        for rank, (cid, text, meta, dist) in enumerate(
            zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            ),
            start=1,
        ):
            score = round(min(1.0, max(0.0, 1.0 - float(dist))), 3)
            hits.append(
                Hit(
                    rank,
                    cid,
                    meta["doc"],
                    meta["title"],
                    meta["section"],
                    int(meta["position"]),
                    text,
                    score,
                )
            )
        hits.sort(key=lambda h: -h.score)
        return [Hit(i, *_tail(h)) for i, h in enumerate(hits, start=1)]

    def list_documents(self) -> list[dict]:
        with self._lock:
            col = self._existing()
            if col is None or col.count() == 0:
                return []
            metas = col.get(include=["metadatas"])["metadatas"]
        by_doc: dict[str, dict] = {}
        for m in sorted(metas, key=lambda m: (m["doc"], int(m["position"]))):
            d = by_doc.setdefault(
                m["doc"],
                {"doc": m["doc"], "title": m["title"], "sections": [], "chunks": 0, "words": 0},
            )
            if m["section"] not in d["sections"]:
                d["sections"].append(m["section"])
            d["chunks"] += 1
            d["words"] += int(m["words"])
        return list(by_doc.values())

    def stats(self) -> dict:
        with self._lock:
            col = self._existing()
            if col is None:
                return {"documents": 0, "chunks": 0, "embedding_model": EMBEDDING_MODEL}
            docs, _ = self._totals(col)
            return {"documents": docs, "chunks": col.count(), "embedding_model": EMBEDDING_MODEL}

    def telemetry_enabled(self) -> bool:
        return bool(self._client.get_settings().anonymized_telemetry)

    @staticmethod
    def _totals(col) -> tuple[int, int]:
        metas = col.get(include=["metadatas"])["metadatas"]
        return len({m["doc"] for m in metas}), sum(int(m["words"]) for m in metas)


def _tail(h: Hit) -> tuple:
    return (h.id, h.doc, h.title, h.section, h.position, h.text, h.score)


def _metadata(c: Chunk) -> dict:
    return {
        "doc": c.doc,
        "title": c.title,
        "section": c.section,
        "position": c.position,
        "words": c.words,
    }
