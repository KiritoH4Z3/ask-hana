# Retrieval eval

Embedding model all-MiniLM-L6-v2, 11 documents, 76 chunks, top-k 4.
Queried straight from the vector store: no server, no language model.

| Metric (answerable, n=26) | Value |
| --- | --- |
| hit@1 | 0.885 |
| hit@4 | 1.0 |
| MRR | 0.936 |

Best score per question:

| Group | n | min | median | max |
| --- | --- | --- | --- | --- |
| answerable | 26 | 0.35 | 0.495 | 0.777 |
| not_answerable | 12 | 0.137 | 0.199 | 0.53 |
| unanswerable | 6 | 0.137 | 0.217 | 0.282 |
| offtopic | 3 | 0.144 | 0.162 | 0.167 |
| injection | 3 | 0.188 | 0.301 | 0.53 |

Chosen MIN_SCORE: **0.33**. Answerable recall 1.000 (floor 0.9), precision of "grounded" 0.963, 1 of 12 unanswerable questions still pass the line (the model then declines them).

Caveat: MIN_SCORE is fitted on these same 38 questions, so recall and precision above are in-sample, not held out. The lowest answerable best score is 0.35, which leaves a margin of 0.02 over the line: a new answerable question phrased less closely to its passage can fall below it and get the not-found reply.
