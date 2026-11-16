# Silent failure this file catches: AI-tell copy (em dashes, spaced en dashes, " -- " used as a
# dash, banned marketing vocabulary, invisible characters) reaching a visitor through a file no
# one proofreads: knowledge docs, the page, the README, docs, or an error message in src/.
#
# The gate proves itself: it plants a violation of every kind in a temp file and demands a hit,
# and it refuses to pass on an empty file set.
#
# Skipped files: a file that does not exist yet is skipped on its own. But the gate fails when
# NEITHER knowledge/ NOR web/ exists, because then it would be vouching for almost nothing.
# Set ASK_HANA_VOICE_STANDALONE=1 to turn that one check into a skip while the content and
# frontend agents are still writing their files; the integrator runs without it.
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ask_hana"

# DESIGN-CRAFT section 11 vocabulary. Spaces match any whitespace run; hyphens are literal.
BANNED_WORDS = [
    "unlock(?:s|ed|ing)?",
    "elevate[sd]?",
    "elevating",
    "empower(?:s|ed|ing|ment)?",
    "leverag(?:e|es|ed|ing)",
    "harness(?:es|ed|ing)?",
    "seamless(?:ly)?",
    "effortless(?:ly)?",
    "robust(?:ness)?",
    "cutting-edge",
    "state-of-the-art",
    "best-in-class",
    "world-class",
    "unparalleled",
    "game-changers?",
    "revolutioniz(?:e|es|ed|ing)",
    "transform the way",
    "supercharg(?:e|es|ed|ing)",
    "streamlin(?:e|es|ed|ing)",
    "next-level",
    "holistic",
    "synergy",
    "delve[sd]?",
    "delving",
    "navigate the complexities",
    "journeys?",
    "curated",
    "crafted with care",
    "designed with you in mind",
    "tailored to your needs",
    "at your fingertips",
    "one-stop",
    "look no further",
    "say goodbye to",
    "welcome to the future of",
    "dive in",
    "a must-have",
    "take it to the next level",
    "peace of mind",
    "hassle-free",
    "no-brainer",
    "ai-powered",
    "in today['\u2019]s (?:fast-paced|ever-evolving)",
    "and everything in between",
]

# Phrase shapes that need a little structure.
BANNED_SHAPES = [
    "the future of [^.!?\\n]{1,40} is here",
    "whether you['\u2019]re an? [^.!?\\n]{1,60}? or an?",
    "it['\u2019]s not just [^.!?\\n]{1,60}?[,;]? it['\u2019]s",
    "ready to [^.!?\\n]{0,60}\\?\\s*let['\u2019]s",
]

# A `\b` after a hyphenated word also matches inside a longer hyphenated word (the hyphen trap),
# so boundaries are explicit lookarounds that treat hyphens and apostrophes as word characters.
_EDGE_L, _EDGE_R = r"(?<![\w-])", r"(?![\w-])"
BANNED = re.compile(
    "|".join(
        f"{_EDGE_L}(?:{p.replace(' ', chr(92) + 's+')}){_EDGE_R}"
        for p in [*BANNED_WORDS, *BANNED_SHAPES]
    ),
    re.IGNORECASE,
)

EM_DASH = "—"
SPACED_EN_DASH = re.compile(r"\s\u2013\s")
# Spaced en dashes that are ranges, not punctuation: digits either side, or two weekday names.
_DAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*"
RANGE_EN_DASH = re.compile(rf"(?:\d\s\u2013\s\d|{_DAY}\s\u2013\s{_DAY})")
SPACED_DOUBLE_HYPHEN = re.compile(r"\s--\s")
# Written as escapes on purpose: raw invisible characters in this file would fail the watermark
# audit, and a formatter that strips them would leave an empty (invalid) character class.
# U+200C and U+200D (Arabic joiners) are left out: they are typography, not marks.
INVISIBLE = re.compile("[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def prose(text: str, suffix: str) -> str:
    """Drop code where ` -- ` is a legitimate CLI separator."""
    if suffix == ".md":
        return INLINE_CODE.sub("", FENCE.sub("", text))
    return text


def violations(text: str, suffix: str = ".md") -> list[str]:
    found = []
    if EM_DASH in text:
        found.append("em dash")
    if INVISIBLE.search(text):
        found.append("invisible character")
    body = prose(text, suffix)
    if SPACED_EN_DASH.search(RANGE_EN_DASH.sub("range", body)):
        found.append("spaced en dash")
    if SPACED_DOUBLE_HYPHEN.search(body):
        found.append("double hyphen used as a dash")
    for match in BANNED.finditer(body):
        found.append(f"banned vocabulary: {match.group(0)!r}")
    return found


def string_constants(path: Path) -> str:
    """All string literals of a module except docstrings (comments are never text)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    parts = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    return "\n".join(parts)


def golden_questions(path: Path) -> str:
    """Only the visitor-facing question text of the golden set, not ids or fact lists."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return "\n".join(r["question"] for r in rows)


def scanned_files() -> list[tuple[Path, str]]:
    """(path, text-to-scan) for every file in the gate's scope that exists."""
    files: list[tuple[Path, str]] = []
    candidates = [
        *sorted((ROOT / "knowledge").glob("*.md")),
        *sorted((ROOT / "web").glob("*.html")),
        *sorted((ROOT / "web").glob("*.js")),
        *sorted((ROOT / "web").glob("*.css")),
        *sorted((ROOT / "web").glob("*.svg")),
        ROOT / "README.md",
        ROOT / ".env.example",
        ROOT / "pyproject.toml",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "eval").rglob("*.md")),
        *sorted((ROOT / "eval").glob("*.yaml")),
        *sorted((ROOT / ".github").rglob("*.yml")),
    ]
    for path in candidates:
        if path.is_file():
            files.append((path, path.read_text(encoding="utf-8")))
    golden = ROOT / "eval" / "golden.jsonl"
    if golden.is_file():
        files.append((golden, golden_questions(golden)))
    for path in [*sorted(SRC.glob("*.py")), *sorted((ROOT / "eval").glob("*.py"))]:
        files.append((path, string_constants(path)))
    return files


# ------------------------------------------------------------------ the gate itself


def test_gate_catches_every_planted_violation(tmp_path):
    planted = {
        "em dash": f"One thing {EM_DASH} another.",
        "spaced en dash": "She dives \u2013 then bakes.",
        "double hyphen used as a dash": "We left -- quickly.",
        "invisible character": "zero" + chr(0x200B) + "width",
        "banned vocabulary": "A seamless, robust journey. Leverage it. Look no further. "
        "Whether you're a diver or a baker. It's not just clay, it's art. "
        "The future of pottery is here. Ready to dive? Let's go. Peace of mind.",
    }
    for name, text in planted.items():
        f = tmp_path / "planted.md"
        f.write_text(text, encoding="utf-8")
        hits = violations(f.read_text(encoding="utf-8"))
        assert any(h.startswith(name) for h in hits), (name, hits)
    many = violations(planted["banned vocabulary"])
    for word in (
        "seamless",
        "robust",
        "journey",
        "leverage",
        "look no further",
        "whether you're",
        "it's not just",
        "the future of pottery is here",
        "ready to dive",
        "peace of mind",
    ):
        assert any(word in h.lower() for h in many), (word, many)


def test_gate_allows_ranges_hyphens_code_and_clean_prose():
    clean = (
        "Open 9:00 – 18:00 is a range, and 2019–2024 is too. Sun–Thu works. "
        "A well-known, hand-thrown bowl. Run `ask-hana -- --help` for flags.\n\n"
        "```\nuv run ask-hana -- --port 3012\n```\n"
        "She is robustly built? No: the word robustness is banned, the hyphen trap is not: "
        "cutting-edgeless and journey-man are different words."
    )
    hits = violations(clean)
    assert not any("dash" in h or "double hyphen" in h for h in hits), hits
    assert not any("cutting" in h or "journey-man" in h for h in hits), hits


def test_hyphen_trap_is_closed():
    assert violations("a robust-looking bowl") == []  # part of a longer hyphenated word
    assert violations("This is robust.") != []
    assert violations("a state-of-the-art kiln") != []
    assert violations("pre-journey notes") == []


def test_gate_scans_string_literals_not_comments_or_docstrings(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(
        f'"""Docstring {EM_DASH} ignored."""\n'
        f"# comment {EM_DASH} ignored\n"
        f'X = "bad {EM_DASH} literal"\n'
    )
    text = string_constants(f)
    assert "bad" in text and "Docstring" not in text and "comment" not in text
    assert violations(text) == ["em dash"]


def test_prompts_module_is_in_scope_and_clean():
    scanned = {p.name for p, _ in scanned_files()}
    assert "prompts.py" in scanned and "errors.py" in scanned


# ------------------------------------------------------------------ the real files


def test_gate_refuses_an_empty_file_set(monkeypatch):
    monkeypatch.setattr(f"{__name__}.SRC", Path("/nonexistent"))
    monkeypatch.setattr(f"{__name__}.ROOT", Path("/nonexistent"))
    assert scanned_files() == []  # the real test below must therefore assert non-empty


def test_site_content_exists():
    has_knowledge = (ROOT / "knowledge").is_dir() and any((ROOT / "knowledge").glob("*.md"))
    has_web = (ROOT / "web").is_dir() and any((ROOT / "web").glob("*.html"))
    if not (has_knowledge or has_web):
        message = (
            "Neither knowledge/*.md nor web/*.html exists, so the voice gate "
            "would check almost nothing."
        )
        if os.environ.get("ASK_HANA_VOICE_STANDALONE") == "1":
            pytest.skip(message)
        pytest.fail(message)


def test_shipped_copy_has_no_ai_tells():
    files = scanned_files()
    assert files, "the voice gate found no files to scan"
    assert any(p.parent == SRC for p, _ in files)
    problems = {}
    for path, text in files:
        found = violations(text, path.suffix)
        if found:
            problems[str(path.relative_to(ROOT))] = found
    assert not problems, problems


# ------------------------------------------------------------------ coverage of the gate itself

TEXT_SUFFIXES = {
    ".md",
    ".html",
    ".js",
    ".css",
    ".py",
    ".jsonl",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".svg",
    ".example",
    ".lock",
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "data",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
# Text files that are deliberately outside the gate, each with its reason.
EXCLUDED = {
    "tests": "plants violations on purpose and holds fixtures",
    "web/fonts": "font licence texts, not product copy",
    "LICENSE": "legal text",
    "uv.lock": "generated lockfile",
    "eval/results/answers.json": "machine output; the prose is in answers.md",
    "eval/results/retrieval.json": "machine output; the prose is in retrieval.md",
    "eval/results/ablation.json": "machine output; the prose is in ablation.md",
    "eval/promptfoo_tests.yaml": "generated from golden.jsonl; its regexes quote refusal phrases",
    "eval/promptfooconfig.yaml": "provider wiring, no visitor copy",
    ".gitignore": "ignore patterns",
    ".python-version": "version pin",
}


def _excluded(rel: str) -> bool:
    return any(rel == key or rel.startswith(key + "/") for key in EXCLUDED)


def test_every_text_file_is_scanned_or_excluded_with_a_reason():
    """Silent failure: a new public file (a report, a config, a doc in a subfolder) sitting
    outside the gate, so an em dash or banned word in it passes."""
    scanned = {p.relative_to(ROOT).as_posix() for p, _ in scanned_files()}
    missing = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if not path.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {
            "LICENSE",
            ".gitignore",
            ".python-version",
        }:
            continue
        if rel.as_posix() not in scanned and not _excluded(rel.as_posix()):
            missing.append(rel.as_posix())
    assert not missing, f"add to scanned_files() or EXCLUDED with a reason: {missing}"


def test_excluded_entries_all_exist():
    stale = [k for k in EXCLUDED if not (ROOT / k).exists()]
    assert not stale, stale


def test_the_gate_scans_the_files_that_used_to_slip_past_it():
    scanned = {p.relative_to(ROOT).as_posix() for p, _ in scanned_files()}
    for rel in (
        "eval/README.md",
        "eval/results/answers.md",
        "eval/results/retrieval.md",
        "eval/golden.jsonl",
        ".env.example",
        "pyproject.toml",
        "web/styles.css",
        "eval/build_promptfoo_tests.py",
        "docs/DESIGN.md",
    ):
        assert rel in scanned, rel


def test_readme_exists_and_is_scanned():
    assert (ROOT / "README.md").is_file()
    assert "README.md" in {p.name for p, _ in scanned_files()}


def test_invisible_character_pattern_has_no_raw_invisibles_in_this_file():
    """Silent failure: raw U+200B/U+FEFF bytes in this file fail `wmr audit-dir`, and a cleaner
    that strips them turns the pattern into an invalid empty class."""
    text = Path(__file__).read_text(encoding="utf-8")
    raw = [hex(ord(c)) for c in text if ord(c) in (0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF, 0xAD)]
    assert raw == []
    assert INVISIBLE.search("a" + chr(0x200B) + "b") and INVISIBLE.search(chr(0xFEFF))
    assert not INVISIBLE.search("\u0645\u200d\u0645")  # Arabic joiner stays allowed
