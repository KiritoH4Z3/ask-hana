"""Shared fixtures. Tests never touch ./data or ./knowledge; they use fixtures and tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from ask_hana.config import Settings
from ask_hana.store import Hit, default_embedder

FIXTURE_KNOWLEDGE = Path(__file__).parent / "fixtures" / "knowledge"


@pytest.fixture(scope="session")
def embedder():
    """One ONNX embedder for the whole run (loading it per test would cost seconds each)."""
    return default_embedder()


@pytest.fixture
def knowledge_dir() -> Path:
    return FIXTURE_KNOWLEDGE


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        knowledge_dir=FIXTURE_KNOWLEDGE,
        chroma_path=tmp_path / "chroma",
        rate_limit_per_minute=100,
    )


def make_hit(n=1, score=0.7, text="Hana free dives on weekends.", **kw) -> Hit:
    base = dict(
        n=n,
        id=f"id{n:014d}",
        doc="hobbies.md",
        title="Hobbies",
        section="Free diving",
        position=n - 1,
        text=text,
        score=score,
    )
    base.update(kw)
    return Hit(**base)
