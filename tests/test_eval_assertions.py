# Silent failures this file catches: promptfoo assertions that pass wrong answers, so a 38/38
# headline overstates quality. Substring fact matching ('9' inside '1970s', 'oud' inside 'cloud'),
# a decline regex satisfied by any "don't" or "isn't" in a grounded hallucination, and a golden
# row with no expected facts passing vacuously. Runs the generated JS under node.
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
spec = importlib.util.spec_from_file_location(
    "build_promptfoo_tests", EVAL / "build_promptfoo_tests.py"
)
build = importlib.util.module_from_spec(spec)
sys.modules["build_promptfoo_tests"] = build
spec.loader.exec_module(build)

RUNNER = """
const [code, output, vars] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const fn = new Function('output', 'context', code);
process.stdout.write(JSON.stringify(fn(output, { vars })));
"""


def grade(code: str, output: dict, expected_facts=()):
    node = shutil.which("node")
    if not node:
        pytest.fail("node is required to run the promptfoo assertion code")
    payload = json.dumps([code, output, {"expected_facts": json.dumps(list(expected_facts))}])
    out = subprocess.run(
        [node, "-e", RUNNER], input=payload, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def src(n=1):
    return {"n": n, "used": True}


def answerable(answer, facts, grounded=True):
    r = {"answer": answer, "grounded": grounded, "sources": [src()]}
    return grade(build.ANSWERABLE, r, facts)["pass"]


def declines(answer, grounded=True):
    return grade(build.DECLINE, {"answer": answer, "grounded": grounded, "sources": []})["pass"]


def test_fact_match_respects_word_and_digit_boundaries():
    assert not answerable("She restores 1970s film cameras [1].", ["9|nine"])
    assert not answerable("She has 19 cameras [1].", ["9|nine"])
    assert not answerable("The cloud was loud [1].", ["oud"])
    assert not answerable("There are 137 components [1].", ["37"])
    assert answerable("She has restored 9 cameras [1].", ["9|nine"])
    assert answerable("She has restored nine cameras [1].", ["9|nine"])
    assert answerable("She plays the oud [1].", ["oud"])
    assert answerable("Tidebook adds 37 components [1].", ["37"])
    assert answerable("The count was 37.", ["37"]) is False  # still needs a citation


def test_harmless_phrasing_variants_are_accepted_through_the_golden_alternates():
    golden = {r["id"]: r for r in map(json.loads, (EVAL / "golden.jsonl").read_text().splitlines())}
    assert answerable("It is a tide table app [1].", golden["q08"]["expected_facts"])
    assert answerable("It produced 2210 photos [1].", golden["q09"]["expected_facts"])
    assert answerable("Her best is 32 metres [1].", golden["q14"]["expected_facts"])
    assert answerable("Her best is 32 m [1].", golden["q14"]["expected_facts"])


def test_decline_rejects_a_confident_wrong_grounded_answer():
    assert not declines("Hana earns AED 20,000 a month and isn't paid weekly [1].")
    assert not declines(
        "Hana earns about AED 240,000 a year, though she doesn't talk about it [1]."
    )
    assert not declines("The capital of France is Paris, nothing more.")


def test_decline_accepts_an_honest_not_found_and_an_ungrounded_reply():
    assert declines("I could not find that in Hana's documents. Try a question about her work.")
    assert declines("The documents do not mention her salary. They do cover her studio.")
    assert declines("anything at all", grounded=False)


def test_an_answerable_golden_row_without_facts_is_refused(tmp_path, monkeypatch):
    bad = tmp_path / "golden.jsonl"
    bad.write_text(
        json.dumps(
            {
                "id": "q99",
                "question": "x?",
                "answerable": True,
                "expected_facts": [],
                "kind": "fact",
            }
        )
        + "\n"
    )
    monkeypatch.setattr(build, "HERE", tmp_path)
    with pytest.raises(SystemExit, match="q99"):
        build.main()


def test_the_shipped_yaml_matches_the_generator():
    before = (EVAL / "promptfoo_tests.yaml").read_text()
    build.main()
    assert (EVAL / "promptfoo_tests.yaml").read_text() == before, (
        "run eval/build_promptfoo_tests.py"
    )
