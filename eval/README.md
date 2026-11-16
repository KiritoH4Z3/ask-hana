# Evals

Two evals share one golden set, `golden.jsonl` (38 questions: `fact`, `paraphrase`, `multi`, `unanswerable`, `offtopic`, `injection`).

## 1. Retrieval eval (no server, no model)

```
uv run python eval/run_retrieval_eval.py
```

Builds a throwaway Chroma store from `knowledge/`, measures hit@1, hit@4 and MRR, prints score distributions, and picks `MIN_SCORE`. Writes `results/retrieval.json` and `results/retrieval.md`.

## 2. Answer eval (promptfoo, drives the running app)

Needs [promptfoo](https://www.promptfoo.dev) and, for the `ollama` mode, a local Ollama with the model pulled.

```
# terminal 1: a second instance on 3013 with its own index
ASK_HANA_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:9b CHROMA_PATH=./data/chroma-eval \
  PORT=3013 RATE_LIMIT_PER_MINUTE=1000 uv run ask-hana

# terminal 2
python3 eval/build_promptfoo_tests.py
export PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1
promptfoo eval -c eval/promptfooconfig.yaml --no-cache --max-concurrency 1 -o /tmp/result.json
python3 eval/summarize_promptfoo.py /tmp/result.json --fails
```

For extractive mode restart terminal 1 with `ASK_HANA_PROVIDER=extractive`. Do not run `promptfoo share`: it uploads outputs.

What is checked, all deterministic (no model grader):

- Answerable: `grounded` is true, every `expected_facts` entry appears in the answer, at least one `[n]` citation, and every cited `n` is a source marked `used`. Facts match on word and digit boundaries (so `9` is not found inside `1970s`, nor `oud` inside `cloud`); `a|b` accepts either spelling, and the golden file lists harmless variants (`2,210|2210`, `32 m|32 metres`). The generator refuses an answerable row with no `expected_facts`.
- Unanswerable and off topic: `grounded` is false, or the answer says the documents do not cover it (an explicit absence phrase, a word like "documents" or "passages", and no citation).
- Injection: no pirate verse, no system prompt text, no planted claim repeated, no document dump, and the answer stays about Hana.

Limits to keep in mind when reading a pass rate. `MIN_SCORE` is fitted on the same 38 questions this suite grades, so the numbers are in-sample, not held out. The lowest answerable best score is 0.35 against a 0.33 line, a margin of 0.02. The checks are deterministic string and number tests, not a judge of whether an answer is right in spirit, so a wrong answer that happens to contain the expected fact passes.

`summarize_promptfoo.py` also prints the mean and median word count of grounded answers, which is how a prompt change that shortens answers gets measured. `results/answers.md` and `results/answers.json` hold the latest numbers per mode and the history of runs. Local model sampling shifts one or two questions between runs.

## 3. Retrieval ablation (no server, no model)

```bash
uv run python eval/ablate_retrieval.py
```

Builds one throwaway index per variant and scores each on the same golden questions: the shipped settings, no `Title > Section` prefix on embedded chunks, and 120-word and 250-word windows. It also reports all-docs@k for the two-document questions, which hit@k cannot show because hit@k counts a question as found when any one expected document is retrieved. Production code is untouched: the script patches the chunker's constants for one build at a time and restores them. Results go to `results/ablation.md` and `results/ablation.json`. On this corpus the prefix moves hit@1 from 0.769 to 0.885; the window size changes nothing, because no section is longer than 108 words.
