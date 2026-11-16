# Silent failures this file catches:
# - a long section embedded as one oversized chunk (retrieval blurs, citations get huge)
# - chunks that lose their section or title (the breadcrumb is what lets "dive" match
#   "Free diving")
# - ids that change between runs for identical input (the index fingerprint and citations drift)
# - empty chunks from blank sections or stray headings (they embed as noise and score randomly)
from __future__ import annotations

from ask_hana.chunking import (
    CHUNKER_VERSION,
    OVERLAP_WORDS,
    WINDOW_WORDS,
    chunk_document,
    chunk_id,
    load_chunks,
    window_section,
)

DOC = """# Sample Title

Intro line before any section.

## First

One short section. It has two sentences.

## Second

- A bullet without a full stop
- Another bullet

## Empty

## Third

Final words here.
"""


def long_body(sentences=60):
    return " ".join(
        f"Sentence number {i} talks about diving and breathing today." for i in range(sentences)
    )


def test_sections_become_chunks_with_titles_and_positions():
    chunks = chunk_document("sample.md", DOC)
    assert [c.section for c in chunks] == ["Overview", "First", "Second", "Third"]
    assert {c.title for c in chunks} == {"Sample Title"}
    assert [c.position for c in chunks] == [0, 1, 2, 3]
    assert all(c.doc == "sample.md" for c in chunks)


def test_no_empty_chunks_and_empty_section_is_dropped():
    chunks = chunk_document("sample.md", DOC)
    assert all(c.text.strip() for c in chunks)
    assert "Empty" not in {c.section for c in chunks}
    assert chunk_document("blank.md", "# Only a title\n\n## Nothing\n") == []


def test_breadcrumb_is_in_the_embedded_text_not_the_display_text():
    chunk = chunk_document("sample.md", DOC)[1]
    assert chunk.embed_text == f"Sample Title > First\n{chunk.text}"
    assert "Sample Title" not in chunk.text


def test_bullets_keep_line_breaks_and_lose_markers():
    chunk = chunk_document("sample.md", DOC)[2]
    assert chunk.text == "A bullet without a full stop\nAnother bullet"


def test_ids_are_stable_and_depend_on_content_and_position():
    a = chunk_document("sample.md", DOC)
    b = chunk_document("sample.md", DOC)
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)
    assert all(len(c.id) == 16 and int(c.id, 16) >= 0 for c in a)
    assert a[0].id == chunk_id("sample.md", 0, a[0].text)
    assert chunk_id("a.md", 0, "x") != chunk_id("b.md", 0, "x")


def test_long_section_is_windowed_with_overlap():
    windows = window_section(long_body())
    assert len(windows) > 2
    for w in windows:
        assert len(w.split()) <= WINDOW_WORDS
    # consecutive windows share text, and every window ends on a sentence boundary
    for first, second in zip(windows, windows[1:], strict=False):
        assert first.endswith(".")
        shared = set(first.split()[-OVERLAP_WORDS - 10 :]) & set(
            second.split()[: OVERLAP_WORDS + 10]
        )
        assert len(shared) >= 5
    # nothing is lost
    assert "Sentence number 59" in windows[-1]
    assert "Sentence number 0 " in windows[0]


def test_windows_always_make_progress_on_one_giant_sentence():
    giant = "word " * 500
    windows = window_section(giant)
    assert len(windows) >= 3
    assert all(0 < len(w.split()) <= WINDOW_WORDS for w in windows)


def test_short_section_is_a_single_chunk():
    assert len(window_section("Tiny. Section.")) == 1


def test_fixture_directory_loads_in_filename_order(knowledge_dir):
    chunks = load_chunks(knowledge_dir)
    assert [c.doc for c in chunks][0] == "about.md"
    assert {c.doc for c in chunks} == {"about.md", "hobbies.md", "travel.md"}
    training = [c for c in chunks if c.section == "Training log"]
    assert len(training) == 2  # the long fixture section is split


def test_missing_directory_yields_no_chunks(tmp_path):
    assert load_chunks(tmp_path / "nope") == []


def test_chunker_version_is_pinned():
    assert CHUNKER_VERSION == "1"


def test_bom_before_the_title_still_sets_the_title_and_no_heading_chunk():
    """Silent failure: a Windows editor's BOM hid '# Title', so the title fell back to the
    filename and the raw heading line was indexed as a retrievable 'Overview' chunk."""
    chunks = chunk_document("a-b.md", "\ufeff# Real Title\n\n## Sec\nHello there.\n")
    assert [(c.title, c.section, c.text) for c in chunks] == [("Real Title", "Sec", "Hello there.")]


def test_crlf_line_endings_chunk_like_lf():
    lf = chunk_document("a.md", "# T\n\n## S\nOne. Two.\n")
    crlf = chunk_document("a.md", "# T\r\n\r\n## S\r\nOne. Two.\r\n")
    assert [(c.title, c.section, c.text) for c in crlf] == [
        (c.title, c.section, c.text) for c in lf
    ]


def test_load_chunks_reads_a_bom_file(tmp_path):
    (tmp_path / "x.md").write_bytes(b"\xef\xbb\xbf# Title\n\n## Sec\nBody text.\n")
    (chunk,) = load_chunks(tmp_path)
    assert chunk.title == "Title" and "#" not in chunk.text
