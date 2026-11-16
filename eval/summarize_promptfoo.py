"""Summarise a promptfoo result JSON: pass rate by kind, latency, failure reasons.

Catches one silent failure: reading the headline pass rate and missing that one kind
(for example injection) fails every time.

Run: python3 eval/summarize_promptfoo.py result.json [--fails]
"""

from __future__ import annotations

import collections
import json
import statistics
import sys


def main() -> None:
    d = json.load(open(sys.argv[1]))
    rows = d["results"]["results"]
    by = collections.defaultdict(lambda: [0, 0])
    lat = []
    words = []
    fails = []
    for r in rows:
        k = (r.get("testCase", {}).get("metadata") or {}).get("kind", "?")
        ok = bool(r.get("success"))
        by[k][0] += ok
        by[k][1] += 1
        out_ = (r.get("response") or {}).get("output")
        if isinstance(out_, str):
            try:
                out_ = json.loads(out_)
            except ValueError:
                out_ = None
        if isinstance(out_, dict) and out_.get("grounded") is True:
            words.append(len(str(out_.get("answer", "")).split()))
        if r.get("latencyMs"):
            lat.append(r["latencyMs"] / 1000)
        if not ok:
            why = (r.get("gradingResult") or {}).get("reason") or r.get("error") or ""
            fails.append((r["testCase"]["description"], why.split("\n")[0][:200]))
    tot = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    lat.sort()
    p90 = lat[int(0.9 * (len(lat) - 1))] if lat else 0
    out = {
        "passed": tot[0],
        "total": tot[1],
        "pass_rate": round(tot[0] / tot[1], 3),
        "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())},
        "latency_median_s": round(statistics.median(lat), 2) if lat else None,
        "latency_p90_s": round(p90, 2),
        "grounded_answers": len(words),
        "answer_words_mean": round(statistics.mean(words), 1) if words else None,
        "answer_words_median": statistics.median(words) if words else None,
    }
    print(json.dumps(out, indent=1))
    if "--fails" in sys.argv:
        for f in fails:
            print(f)


if __name__ == "__main__":
    main()
