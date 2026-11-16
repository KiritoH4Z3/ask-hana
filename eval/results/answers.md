# Answer eval

38 golden questions (26 answerable, 6 unanswerable, 3 off topic, 3 injection) sent over HTTP to a running instance and graded by deterministic checks (`eval/promptfoo_tests.yaml`, generated from `eval/golden.jsonl`). Retrieval over `all-MiniLM-L6-v2`, `MIN_SCORE` 0.33, top-k 4.

The threshold and the golden set are the same 38 questions: the numbers are in-sample, not held out, and the lowest answerable best score is 0.35 against the 0.33 line (a margin of 0.02). The checks are string and number tests, so a wrong answer that contains the expected fact passes.

## Results by mode (latest runs)

| Mode | Pass rate | fact | paraphrase | multi | unanswerable | offtopic | injection | Median latency | p90 latency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama, qwen3.5:9b (review run 1) | 38/38 (1.00) | 10/10 | 13/13 | 3/3 | 6/6 | 3/3 | 3/3 | 4.31 s | 5.56 s |
| ollama, qwen3.5:9b (review run 2) | 37/38 (0.97) | 10/10 | 12/13 | 3/3 | 6/6 | 3/3 | 3/3 | 4.35 s | 6.0 s |
| extractive (no model) | 31/38 (0.82) | 10/10 | 9/13 | 0/3 | 6/6 | 3/3 | 3/3 | 0.16 s | 0.17 s |

Real band for the 9b model: 37/38 to 38/38. Sampling at temperature 0.2 moves a question between runs.

## Answer length: the prompt change (review pass)

The model padded answers with sentences about what the documents do not mention. One positively phrased change in `prompts.py`: from "in about 100 words or fewer" to "two to four sentences that address the question, ending once it is answered". Kept, because both runs stayed at 37/38 or better and the mean answer length dropped.

| Prompt | Run | Pass rate | Mean words per grounded answer | Median words | Median latency |
| --- | --- | --- | --- | --- | --- |
| before: about 100 words or fewer | 1 | 35/38 | 68.9 | 69 | 6.85 s |
| before: about 100 words or fewer | 2 | 38/38 | 71.3 | 74 | 6.65 s |
| after: two to four sentences, ending once answered | 1 | 38/38 | 42.8 | 42 | 4.31 s |
| after: two to four sentences, ending once answered | 2 | 37/38 | 44.6 | 43 | 4.35 s |

Words are counted over the 27 grounded answers of each run. Before run 1 scored 35/38 because the stricter fact check (word and digit boundaries) met a golden file that did not yet list "meters" for q14, q15 and q26; the variants were added to `golden.jsonl` and run 2 followed. After run 2 missed q16 on "4 minutes and 10 seconds"; that variant is now in `golden.jsonl` too and that run was not repeated. Some answers still end with a sentence about what the documents do not say; the change shortened them, it did not remove them.

Citations are post-processed for every generator: a run of repeated `[n]` markers to the same source keeps only the last one (`collapse_repeated_citations` in `prompts.py`). The runs above include it.

## Ollama runs over time

| Run | Pass rate | Failures |
| --- | --- | --- |
| baseline 1 | 36/38 (0.947) | q12 (answer said "nine", golden wanted "9 so far"), q16 (a phrasing variant of "4 minutes 10 seconds") |
| baseline 2 | 37/38 (0.974) | q12, same cause |
| final (build phase) | 38/38 (1.00) | none, after q12's golden fact became `9\|nine` |
| review, old prompt, run 1 | 35/38 (0.921) | q14, q15, q26 ("meters" spelling, golden lacked it) |
| review, old prompt, run 2 | 38/38 (1.000) | none |
| review, new prompt, run 1 | 38/38 (1.000) | none |
| review, new prompt, run 2 | 37/38 (0.974) | q16 ("4 minutes and 10 seconds") |

## Extractive mode

Before the review pass extractive scored 30/38. It now scores 31/38 after three changes: a FAQ question line ("Where do you live?") is never quoted as the answer, its words count toward the answer sentence after it; the answer opens with "From Hana's pages:" so first-person text reads as a quote; and repeated citations collapse. It still misses when the answer is spread over two passages (all 3 multi-part questions) and when the best quoted sentence is not the one holding the fact (q12, q13, q20, q21). Extractive mode quotes, it does not reason.

## Not measured

Tone, and the Claude provider (no API key on the build machine).
