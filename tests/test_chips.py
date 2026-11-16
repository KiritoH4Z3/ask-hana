# Silent failure this file catches: a suggested-question chip on the page that retrieval scores
# below MIN_SCORE, so the first thing a visitor clicks returns the not-found copy in every mode
# ("Does Hana have a pet?" scored 0.225 against a 0.33 line). Uses the real knowledge folder
# and the real embedder, so a copy edit that weakens a passage turns this red.
from __future__ import annotations

import re
from pathlib import Path

from ask_hana.config import Settings
from ask_hana.generate import ExtractiveGenerator
from ask_hana.store import VectorStore

ROOT = Path(__file__).resolve().parents[1]


def chips() -> list[str]:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    return re.findall(r'data-q="([^"]+)"', html)


def test_every_suggested_chip_clears_the_threshold_and_is_answered(tmp_path, embedder):
    questions = chips()
    assert len(questions) >= 6, questions
    store = VectorStore(tmp_path / "chroma", ROOT / "knowledge", embedder)
    store.ensure_index()
    settings = Settings()
    for q in questions:
        hits = store.query(q, settings.top_k)
        top = max(h.score for h in hits)
        assert top >= settings.min_score, (q, round(top, 3))
        used = [h for h in hits if h.score >= settings.min_score]
        answer = ExtractiveGenerator().generate(q, used)
        assert answer and "?" not in answer, (q, answer)
