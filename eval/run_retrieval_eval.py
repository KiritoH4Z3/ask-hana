# ruff: noqa: E501
"""Retrieval eval: queries the vector store directly (no server, no LLM).

Catches two silent failures: the right document missing from the top-k
(hit@k, MRR), and a MIN_SCORE that either refuses answerable questions or
lets unanswerable ones through as "grounded".

Run: uv run python eval/run_retrieval_eval.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ask_hana.config import load_settings  # noqa: E402
from ask_hana.store import VectorStore  # noqa: E402

MIN_RECALL = 0.90


def dist(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    return {
        "n": len(s),
        "min": round(s[0], 3),
        "median": round(statistics.median(s), 3),
        "max": round(s[-1], 3),
    }


def main() -> None:
    settings = load_settings()
    items = [
        json.loads(line)
        for line in (ROOT / "eval" / "golden.jsonl").read_text().splitlines()
        if line.strip()
    ]
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(Path(tmp) / "chroma", ROOT / "knowledge")
        report = store.rebuild()
        rows = []
        for it in items:
            hits = store.query(it["question"], settings.top_k)
            top = hits[0].score if hits else 0.0
            docs = [h.doc for h in hits]
            rank = next(
                (i for i, d in enumerate(docs, 1) if d in it.get("expected_docs", [])), None
            )
            rows.append({**it, "top_score": top, "docs": docs, "rank": rank})

    ans = [r for r in rows if r["answerable"]]
    non = [r for r in rows if not r["answerable"]]
    hit1 = sum(1 for r in ans if r["rank"] == 1) / len(ans)
    hitk = sum(1 for r in ans if r["rank"] is not None) / len(ans)
    mrr = sum((1 / r["rank"]) if r["rank"] else 0 for r in ans) / len(ans)

    sweep = []
    for i in range(0, 101):
        t = i / 100
        tp = sum(1 for r in ans if r["top_score"] >= t)
        fp = sum(1 for r in non if r["top_score"] >= t)
        recall = tp / len(ans)
        precision = tp / (tp + fp) if tp + fp else 1.0
        sweep.append((t, precision, recall, fp))
    ok = [s for s in sweep if s[2] >= MIN_RECALL]
    best = max(ok, key=lambda s: (s[1], s[0]))
    # Several thresholds tie on precision: take the middle of that plateau so the
    # line keeps a margin on both sides (the top edge sits on the weakest answerable score).
    plateau = sorted((s for s in ok if s[1] == best[1] and s[3] == best[3]), key=lambda s: s[0])
    chosen = plateau[len(plateau) // 2]
    t, p, rc, fp = chosen

    by_kind: dict[str, list[float]] = {}
    for r in non:
        by_kind.setdefault(r["kind"], []).append(r["top_score"])
    out = {
        "index": {
            "documents": report.documents,
            "chunks": report.chunks,
            "words": report.words,
            "seconds": round(report.seconds, 2),
        },
        "top_k": settings.top_k,
        "answerable": len(ans),
        "hit_at_1": round(hit1, 3),
        "hit_at_k": round(hitk, 3),
        "mrr": round(mrr, 3),
        "max_score": {
            "answerable": dist([r["top_score"] for r in ans]),
            "not_answerable": dist([r["top_score"] for r in non]),
            **{k: dist(v) for k, v in by_kind.items()},
        },
        "chosen_min_score": t,
        "at_chosen": {
            "precision": round(p, 3),
            "recall": round(rc, 3),
            "false_grounded": fp,
            "of_not_answerable": len(non),
        },
        "misses": [
            {"id": r["id"], "q": r["question"], "expected": r["expected_docs"], "got": r["docs"]}
            for r in ans
            if r["rank"] is None
        ],
        "not_rank1": [r["id"] for r in ans if r["rank"] not in (1, None)],
        "low_answerable": sorted([(r["id"], r["top_score"]) for r in ans], key=lambda x: x[1])[:5],
        "high_unanswerable": sorted(
            [(r["id"], r["kind"], r["top_score"]) for r in non], key=lambda x: -x[2]
        )[:5],
    }
    res = ROOT / "eval" / "results"
    res.mkdir(parents=True, exist_ok=True)
    (res / "retrieval.json").write_text(json.dumps(out, indent=2) + "\n")
    md = f"""# Retrieval eval

Embedding model all-MiniLM-L6-v2, {out["index"]["documents"]} documents, {out["index"]["chunks"]} chunks, top-k {out["top_k"]}.
Queried straight from the vector store: no server, no language model.

| Metric (answerable, n={len(ans)}) | Value |
| --- | --- |
| hit@1 | {out["hit_at_1"]} |
| hit@{out["top_k"]} | {out["hit_at_k"]} |
| MRR | {out["mrr"]} |

Best score per question:

| Group | n | min | median | max |
| --- | --- | --- | --- | --- |
"""
    for k, v in out["max_score"].items():
        md += f"| {k} | {v['n']} | {v.get('min')} | {v.get('median')} | {v.get('max')} |\n"
    md += f"""
Chosen MIN_SCORE: **{t:.2f}**. Answerable recall {rc:.3f} (floor {MIN_RECALL}), precision of "grounded" {p:.3f}, {fp} of {len(non)} unanswerable questions still pass the line (the model then declines them).

Caveat: MIN_SCORE is fitted on these same {len(ans) + len(non)} questions, so recall and precision above are in-sample, not held out. The lowest answerable best score is {min(r["top_score"] for r in ans):.2f}, which leaves a margin of {min(r["top_score"] for r in ans) - t:.2f} over the line: a new answerable question phrased less closely to its passage can fall below it and get the not-found reply.
"""
    (res / "retrieval.md").write_text(md)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
