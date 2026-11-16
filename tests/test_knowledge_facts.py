# Silent failure this file catches: two passages of the knowledge base that disagree with each
# other, so a grounded answer contradicts itself. The reef survey said "a photo every metre" on a
# 25 metre tape (about 25 photos) next to a total of 2,210 photos over 38 transects (about 58).
from __future__ import annotations

import re
from pathlib import Path

KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge"


def test_reef_survey_photo_arithmetic_is_consistent():
    text = (KNOWLEDGE / "projects.md").read_text(encoding="utf-8")
    transects = int(re.search(r"laid (\d+) transects", text).group(1))
    photos = int(re.search(r"took ([\d,]+) photos", text).group(1).replace(",", ""))
    tape = int(re.search(r"(\d+) metre tape", text).group(1))
    per_tape = round(photos / transects)
    stated = re.search(r"about (\d+) per tape", text)
    assert stated, "the method sentence must state the per-tape rate"
    assert int(stated.group(1)) == per_tape, (stated.group(1), per_tape)
    assert "photo every metre" not in text
    # Overlapping frames: more photos than metres of tape, which is why "every metre" was wrong.
    assert per_tape > tape
