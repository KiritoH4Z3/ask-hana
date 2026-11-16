# Silent failures this file catches:
# - telemetry left on (anonymised or not, a public demo must not phone home)
# - scores outside [0, 1] or ordered ascending (the UI draws a confidence line from them)
# - a fingerprint that never changes (edited documents keep serving stale answers)
# - a fingerprint that always changes (every start re-embeds everything)
# - a missing knowledge directory crashing startup instead of logging and serving nothing
from __future__ import annotations

import shutil

import pytest

from ask_hana.store import COLLECTION, EMBEDDING_MODEL, VectorStore, fingerprint


@pytest.fixture
def store(tmp_path, knowledge_dir, embedder):
    return VectorStore(tmp_path / "chroma", knowledge_dir, embedder)


def test_build_reports_documents_chunks_words(store):
    report = store.ensure_index()
    assert report.rebuilt is True
    assert (report.documents, report.chunks) == (3, 9)
    assert report.words > 300


def test_query_orders_by_score_with_valid_scores_and_ranks(store):
    store.ensure_index()
    hits = store.query("How deep can Hana free dive?", 4)
    assert len(hits) == 4
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert all(round(s, 3) == s for s in scores)
    assert [h.n for h in hits] == [1, 2, 3, 4]
    assert hits[0].section == "Free diving"
    assert hits[0].doc == "hobbies.md"
    assert "32 metres" in hits[0].text


def test_unrelated_question_scores_below_a_related_one(store):
    store.ensure_index()
    related = store.query("Where has Hana travelled?", 1)[0].score
    unrelated = store.query("Explain how to configure a kubernetes ingress controller", 1)[0].score
    assert related > unrelated + 0.1


def test_k_larger_than_collection_is_clamped(store):
    store.ensure_index()
    assert len(store.query("pottery", 8)) == 8
    assert len(store.query("pottery", 1)) == 1


def test_unchanged_documents_skip_rebuild(store):
    first = store.ensure_index()
    second = store.ensure_index()
    assert first.rebuilt and not second.rebuilt
    assert (second.documents, second.chunks, second.words) == (
        first.documents,
        first.chunks,
        first.words,
    )


def test_reopening_the_same_path_skips_rebuild(tmp_path, knowledge_dir, embedder):
    VectorStore(tmp_path / "c", knowledge_dir, embedder).ensure_index()
    again = VectorStore(tmp_path / "c", knowledge_dir, embedder).ensure_index()
    assert again.rebuilt is False


def test_changed_document_triggers_rebuild(tmp_path, knowledge_dir, embedder):
    docs = tmp_path / "docs"
    shutil.copytree(knowledge_dir, docs)
    s = VectorStore(tmp_path / "c", docs, embedder)
    s.ensure_index()
    (docs / "travel.md").write_text(
        "# Travel\n\n## Trips\n\nHana visited Iceland and saw a glacier.\n"
    )
    report = s.ensure_index()
    assert report.rebuilt is True
    hits = s.query("glacier in Iceland", 1)
    assert hits[0].doc == "travel.md" and "Iceland" in hits[0].text
    assert not any("Oman" in h.text for h in s.query("Oman", 8) if h.doc == "travel.md")


def test_fingerprint_changes_with_content_and_name(tmp_path, knowledge_dir):
    docs = tmp_path / "d"
    shutil.copytree(knowledge_dir, docs)
    base = fingerprint(docs)
    assert fingerprint(docs) == base
    (docs / "about.md").write_text("# About\n\nChanged.\n")
    changed = fingerprint(docs)
    assert changed != base
    (docs / "about.md").rename(docs / "renamed.md")
    assert fingerprint(docs) != changed


def test_rebuild_always_rebuilds(store):
    store.ensure_index()
    assert store.rebuild().rebuilt is True
    assert store.stats()["chunks"] == 9


def test_collection_is_cosine_and_named(store):
    store.ensure_index()
    col = store._client.get_collection(COLLECTION)
    assert col.configuration_json["hnsw"]["space"] == "cosine"
    assert col.metadata["embedding_model"] == EMBEDDING_MODEL


def test_telemetry_is_off(store):
    assert store.telemetry_enabled() is False


def test_list_documents_shape(store):
    store.ensure_index()
    docs = {d["doc"]: d for d in store.list_documents()}
    assert set(docs) == {"about.md", "hobbies.md", "travel.md"}
    hobbies = docs["hobbies.md"]
    assert hobbies["title"] == "Hobbies"
    assert hobbies["sections"] == ["Free diving", "Training log", "Baking"]
    assert hobbies["chunks"] == 4
    assert hobbies["words"] > 250


def test_missing_knowledge_dir_starts_empty_and_logs(tmp_path, embedder, caplog):
    s = VectorStore(tmp_path / "c", tmp_path / "missing", embedder)
    with caplog.at_level("WARNING", logger="ask_hana.store"):
        report = s.ensure_index()
    assert report.chunks == 0
    assert "No markdown documents found" in caplog.text
    assert s.query("anything", 4) == []
    assert s.list_documents() == []
    assert s.stats()["chunks"] == 0


def test_documents_that_appear_later_are_indexed_on_first_query(tmp_path, embedder):
    docs = tmp_path / "docs"
    s = VectorStore(tmp_path / "c", docs, embedder)
    s.ensure_index()
    docs.mkdir()
    (docs / "a.md").write_text("# A\n\n## Pets\n\nHana owns a cat named Biscuit.\n")
    hits = s.query("What is the cat called?", 2)
    assert hits and "Biscuit" in hits[0].text
