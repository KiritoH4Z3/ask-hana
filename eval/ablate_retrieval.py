# ruff: noqa: E501
"""Retrieval ablation: is each chunking choice earning its place?

Catches a silent failure the main retrieval eval cannot: a design choice (the
"Title > Section" prefix on embedded text, the 180-word window) that looks sensible
but makes no difference, or makes retrieval worse. Each variant builds its own
throwaway index from knowledge/ and is scored on the same golden questions.

It also reports all-docs@k for the multi-document questions: hit@k counts a question
as found when ANY expected document is in the top k, which cannot show whether a
two-part question got both of its documents.

Production code is not changed: variants patch the chunker's module constants and
Chunk.embed_text for the duration of one build, then restore them.

Run: uv run python eval/ablate_retrieval.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_hana import chunking  # noqa: E402
from ask_hana.config import load_settings  # noqa: E402
from ask_hana.store import VectorStore  # noqa: E402

PREFIXED = chunking.Chunk.embed_text
PLAIN = property(lambda self: self.text)

VARIANTS = [
    {"name": "shipped: prefix, 180-word windows", "prefix": True, "window": 180, "overlap": 40},
    {"name": "no Title > Section prefix", "prefix": False, "window": 180, "overlap": 40},
    {"name": "prefix, 120-word windows", "prefix": True, "window": 120, "overlap": 30},
    {"name": "prefix, 250-word windows", "prefix": True, "window": 250, "overlap": 50},
]


def score(variant: dict, items: list[dict], top_k: int) -> dict:
    saved = (chunking.WINDOW_WORDS, chunking.OVERLAP_WORDS)
    chunking.WINDOW_WORDS, chunking.OVERLAP_WORDS = variant["window"], variant["overlap"]
    chunking.Chunk.embed_text = PREFIXED if variant["prefix"] else PLAIN
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = VectorStore(Path(tmp) / "chroma", ROOT / "knowledge")
            report = store.rebuild()
            rows = []
            for it in items:
                hits = store.query(it["question"], top_k)
                docs = [h.doc for h in hits]
                expected = it.get("expected_docs", [])
                rank = next((i for i, d in enumerate(docs, 1) if d in expected), None)
                rows.append(
                    {
                        **it,
                        "rank": rank,
                        "top": hits[0].score if hits else 0.0,
                        "all_docs": bool(expected) and all(d in docs for d in expected),
                    }
                )
    finally:
        chunking.WINDOW_WORDS, chunking.OVERLAP_WORDS = saved
        chunking.Chunk.embed_text = PREFIXED

    ans = [r for r in rows if r["answerable"]]
    non = [r for r in rows if not r["answerable"]]
    multi = [r for r in ans if r["kind"] == "multi"]
    n = len(ans)
    return {
        "variant": variant["name"],
        "chunks": report.chunks,
        "hit_at_1": round(sum(r["rank"] == 1 for r in ans) / n, 3),
        "hit_at_k": round(sum(r["rank"] is not None for r in ans) / n, 3),
        "mrr": round(sum(1 / r["rank"] if r["rank"] else 0 for r in ans) / n, 3),
        "multi_all_docs_at_k": f"{sum(r['all_docs'] for r in multi)}/{len(multi)}",
        "weakest_answerable_top": round(min(r["top"] for r in ans), 3),
        "strongest_unanswerable_top": round(
            max(r["top"] for r in non if r["kind"] != "injection"), 3
        ),
    }


def main() -> None:
    top_k = load_settings().top_k
    items = [
        json.loads(line)
        for line in (ROOT / "eval" / "golden.jsonl").read_text().splitlines()
        if line.strip()
    ]
    results = [score(v, items, top_k) for v in VARIANTS]
    longest = max(
        len(body.split())
        for path in chunking.knowledge_files(ROOT / "knowledge")
        for _, body in chunking.parse_sections(path.read_text(encoding="utf-8-sig"), path.stem)[1]
    )

    out_dir = ROOT / "eval" / "results"
    (out_dir / "ablation.json").write_text(
        json.dumps({"top_k": top_k, "results": results}, indent=2) + "\n"
    )
    lines = [
        "# Retrieval ablation",
        "",
        f"Same 38 golden questions, top-k {top_k}, all-MiniLM-L6-v2, one throwaway index per variant. "
        "`all-docs@k` counts the multi-document questions whose expected documents ALL appear in the top k. "
        "The last two columns show the gap the answer-or-decline line has to sit in "
        "(injection questions excluded from the unanswerable column, since they are not about Hana at all).",
        "",
        "| Variant | Chunks | hit@1 | hit@k | MRR | multi all-docs@k | weakest answerable | strongest unanswerable |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['variant']} | {r['chunks']} | {r['hit_at_1']} | {r['hit_at_k']} | {r['mrr']} | "
            f"{r['multi_all_docs_at_k']} | {r['weakest_answerable_top']} | {r['strongest_unanswerable_top']} |"
        )
    lines += [
        "",
        f"The longest section in knowledge/ is {longest} words. A window only splits a section longer than itself, "
        f"so window sizes from {longest} words up produce identical chunks here: on this corpus the window setting is untested, "
        "and only the prefix moves the numbers.",
        "",
        "In-sample, like every number in this folder: the variants are compared on the questions the shipped settings were chosen with.",
        "",
        "Run: `uv run python eval/ablate_retrieval.py`",
    ]
    (out_dir / "ablation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
