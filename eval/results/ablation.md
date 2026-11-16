# Retrieval ablation

Same 38 golden questions, top-k 4, all-MiniLM-L6-v2, one throwaway index per variant. `all-docs@k` counts the multi-document questions whose expected documents ALL appear in the top k. The last two columns show the gap the answer-or-decline line has to sit in (injection questions excluded from the unanswerable column, since they are not about Hana at all).

| Variant | Chunks | hit@1 | hit@k | MRR | multi all-docs@k | weakest answerable | strongest unanswerable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| shipped: prefix, 180-word windows | 76 | 0.885 | 1.0 | 0.936 | 3/3 | 0.35 | 0.282 |
| no Title > Section prefix | 76 | 0.769 | 1.0 | 0.865 | 3/3 | 0.325 | 0.263 |
| prefix, 120-word windows | 76 | 0.885 | 1.0 | 0.936 | 3/3 | 0.35 | 0.282 |
| prefix, 250-word windows | 76 | 0.885 | 1.0 | 0.936 | 3/3 | 0.35 | 0.282 |

The longest section in knowledge/ is 108 words. A window only splits a section longer than itself, so window sizes from 108 words up produce identical chunks here: on this corpus the window setting is untested, and only the prefix moves the numbers.

In-sample, like every number in this folder: the variants are compared on the questions the shipped settings were chosen with.

Run: `uv run python eval/ablate_retrieval.py`
