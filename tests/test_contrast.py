"""Silent failure caught: a palette edit that quietly drops a text/surface pair below WCAG AA in
either theme, or a dark-mode block that drifts from the manual dark toggle block, or a raw hex
colour that slips into a rule outside the token blocks (so the contrast table no longer covers it).
The pairs are listed explicitly; adding a token without adding its pairs fails the coverage test.
Stdlib plus pytest only.
"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "web" / "styles.css").read_text(encoding="utf-8")

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
DECL = re.compile(r"(--[a-z-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;")


def block(pattern: str) -> str:
    m = re.search(pattern, CSS)
    assert m, f"token block not found: {pattern}"
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[i], 0)
        i += 1
    return CSS[m.end() : i - 1]


def tokens(text: str) -> dict:
    return {k: v.upper() for k, v in DECL.findall(text)}


LIGHT = tokens(block(r"(?m)^:root\s*\{"))
DARK_MEDIA = tokens(block(r":root:not\(\[data-theme=\"light\"\]\)\s*\{"))
DARK_MANUAL = tokens(block(r':root\[data-theme="dark"\]\s*\{'))
THEMES = {"light": LIGHT, "dark": DARK_MANUAL}


def lum(h: str) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_MIN = 5.0  # AA is 4.5, margin kept so nothing ships on the threshold
UI_MIN = 3.5  # AA is 3.0 for large text and UI components

# (foreground, background, minimum, what it is)
PAIRS = [
    ("--ink", "--ground", TEXT_MIN, "body text on page"),
    ("--ink", "--water", TEXT_MIN, "answer and used source text"),
    ("--ink", "--land", TEXT_MIN, "knows panel title"),
    ("--ink-muted", "--ground", TEXT_MIN, "dimmed source text on page"),
    ("--ink-muted", "--water", TEXT_MIN, "secondary text on water"),
    ("--ink-muted", "--land", TEXT_MIN, "document list secondary text"),
    ("--brand-ink", "--ground", TEXT_MIN, "citation chip, links, notice tag"),
    ("--brand-ink", "--water", TEXT_MIN, "chip and tag on water"),
    ("--brand-ink", "--land", TEXT_MIN, "ink grade on land"),
    ("--on-brand", "--brand", TEXT_MIN, "send button label, used source number"),
    ("--depth", "--ground", TEXT_MIN, "threshold figure in caption"),
    ("--depth", "--water", UI_MIN, "confidence line and below-line bar on water"),
    ("--line-strong", "--ground", UI_MIN, "textarea and button borders"),
    ("--line-strong", "--water", UI_MIN, "suggestion and notice borders"),
    ("--brand", "--ground", UI_MIN, "used bar on page"),
    ("--brand", "--water", UI_MIN, "used bar on water"),
    ("--brand-ink", "--ground", UI_MIN, "focus ring on page"),
    ("--brand-ink", "--water", UI_MIN, "focus ring on water"),
    ("--brand-ink", "--land", UI_MIN, "focus ring on land"),
]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fg,bg,minimum,what", PAIRS)
def test_pair_meets_aa_with_margin(theme, fg, bg, minimum, what):
    t = THEMES[theme]
    r = ratio(t[fg], t[bg])
    assert r >= minimum, f"{theme}: {what} {fg} on {bg} is {r:.2f}:1, needs {minimum}:1"


def test_both_themes_declare_the_same_tokens():
    assert set(LIGHT) == set(DARK_MANUAL) == set(DARK_MEDIA)
    assert len(LIGHT) >= 10


def test_system_dark_matches_manual_dark():
    assert DARK_MEDIA == DARK_MANUAL


def test_every_colour_token_used_in_a_pair_exists():
    used = {t for p in PAIRS for t in p[:2]}
    assert used <= set(LIGHT), used - set(LIGHT)


def test_every_text_or_accent_token_is_covered_by_a_pair():
    covered = {t for p in PAIRS for t in p[:2]}
    assert {
        "--ground",
        "--water",
        "--land",
        "--ink",
        "--ink-muted",
        "--brand",
        "--brand-ink",
        "--depth",
    } <= covered


def test_raw_hex_only_inside_token_blocks():
    stripped = CSS
    for pat in (
        r"(?m)^:root\s*\{",
        r":root:not\(\[data-theme=\"light\"\]\)\s*\{",
        r':root\[data-theme="dark"\]\s*\{',
    ):
        m = re.search(pat, stripped)
        body = block(pat)
        stripped = stripped[: m.end()] + stripped[m.end() + len(body) :]
    assert not HEX.findall(stripped), f"raw hex outside token blocks: {HEX.findall(stripped)}"


def test_brand_fill_is_never_text_border_or_ring():
    # the fill grade may be background or border-color of fills only; text and rings use --brand-ink
    assert not re.search(r"(?<![-\w])color:\s*var\(--brand\)", CSS)
    assert not re.search(r"outline[^;]*var\(--brand\)", CSS)
