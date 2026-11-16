"""`ask-hana-ingest`: rebuild the vector index from the knowledge directory."""

from __future__ import annotations

import logging
import sys

from .config import load_settings
from .errors import ConfigError
from .store import VectorStore


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"ask-hana-ingest cannot start: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    store = VectorStore(settings.chroma_path, settings.knowledge_dir)
    report = store.rebuild()
    print(f"documents: {report.documents}")
    print(f"chunks:    {report.chunks}")
    print(f"words:     {report.words}")
    print(f"seconds:   {report.seconds:.2f}")
    if report.chunks == 0:
        print(f"No .md files found in {settings.knowledge_dir}.", file=sys.stderr)
        raise SystemExit(1)
