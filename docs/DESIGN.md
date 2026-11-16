# Ask Hana: design contract

Scaled DESIGN-PROCESS for a one-page demo (see section 13). Every later change edits this file first.

## 1. Design read, thesis, directions

**Reading this as:** a one-page RAG chat demo for recruiters, developers judging retrieval quality and curious visitors, with a calm technical-instrument language, leaning toward nautical chart and ECDIS conventions built in native CSS.

**Dials.** DESIGN_VARIANCE 5 (one asymmetric chat plus side panel, nothing wild; the page is a tool). MOTION_INTENSITY 3 (one sonar ping while waiting, focus and highlight transitions, nothing decorative). VISUAL_DENSITY 5 (scores, documents and passages need to sit close, but the answer stays the loudest thing).

**Thesis.** Hana is a hydrographic surveyor, and a RAG answer is a sounding: a measured value taken at a known place, trusted only where the measurement is good enough. The page demos one verb: answer from the documents and show where the answer came from. Under every answer the retrieved passages appear as soundings with a similarity score and a bar against a confidence line. That line is the API threshold, drawn like a depth contour.

**Three directions.**
1. **Chart room (chosen).** Chart paper ground, land tint, shallow-water tint, chart magenta reserved for what is used, the ECDIS night palette as dark mode, mono numerals for soundings. Signature: the sounding list.
2. **Field notebook.** Plain white page, handwritten-feeling serif, passages as footnotes. Lost: it is the default "personal site" look, the serif discipline rule forbids it without a brand reason, and footnotes hide the retrieval, which is the point of the demo.
3. **Terminal inspector.** Near-black, mono everywhere, JSON-style source panes. Lost: it speaks to developers only, reads as the AI default (near-black plus one acid accent), and recruiters bounce off it.

**Why chart room fits.** The fiction already lives in Fujairah, a survey is literally measuring and judging confidence, and a confidence threshold maps cleanly onto a depth contour. It is specific to this product: it would not work unchanged on a competitor's RAG demo.

## 2. References

Read from `~/.claude/references/awesome-design-md/design-md/`: `ollama` and `linear.app`. Live galleries and screenshots were not captured (scaled step, section 13).
- **ollama.** Signature: a README-like page with one pill action. Type and palette: system sans, flat neutrals, hairline borders, no gradient. Borrowed: flat canvas with thin-border containers and no ornament, so the retrieved passages carry the visual weight. Avoid: pill-everything shapes (we use one 6px radius).
- **linear.app.** Signature: dense panels with hairline borders on a quiet canvas. Type and palette: tight display tracking, one chromatic accent used only on the brand mark, focus rings and intentional actions. Borrowed: the accent appears only where it means something (here: used sources, the send button, focus). Avoid: the near-black default and lavender; our dark mode is the ECDIS night palette.
- **Nautical chart (paper and ECDIS), as a non-web reference.** Signature: soundings and contours on chart paper; magenta for what a navigator must not miss; a night palette that dims everything but keeps magenta. Borrowed: the whole palette logic and the mono numeral layer.

## 3. Colour palette and roles

Eleven colour tokens, each with a job. Everything else is banned (a test fails on raw hex outside the token blocks). ROOM tokens flip with the theme; MATERIAL tokens do not change meaning.

| Token | Light (chart paper) | Dark (night) | Class | Job |
|---|---|---|---|---|
| `--ground` | #F2F5F4 | #0B1519 | room | page background |
| `--water` | #DDECEF | #12232A | room | shallow-water tint: answer and source surfaces |
| `--land` | #E8E5D8 | #1B211E | room | land tint: the "What it knows" panel only |
| `--ink` | #12232B | #D7E4E7 | room | body text |
| `--ink-muted` | #43575F | #9DB4BA | room | secondary text, dimmed sources (never opacity) |
| `--brand` / `--brand-ink` | #B0197F / #8F1166 | #E85DBA / #F08AD0 | material | chart magenta. Fill grade for button, bar, chip fill; ink grade for any text, border or ring |
| `--depth` | #1D5B73 | #7EC3DB | room | reserved secondary: the below-the-line bars and the confidence line |
| `--line` | #B8CACE | #25404A | room | hairline borders on answer, source and notice surfaces |
| `--line-strong` | #5F7A83 | #6E8E98 | room | input and control borders (UI 3:1) |
| `--on-brand` | #FFFFFF | #1A0613 | material | text on a brand fill |

Rules: the brand fill is never text, border or ring (the ink grade is). Status never relies on colour alone: used sources carry the word "Used", below-line sources the word "Below the line", errors carry the word "Problem" in front of the message (a word, not a glyph). Focus ring is `--brand-ink`, 3px, offset 2px, and resolves per surface through the same token. Contrast pairs are listed explicitly in `tests/test_contrast.py` and asserted for both themes with margin (text at least 5:1, large text and UI at least 3.5:1).

## 4. Typography

Self-hosted woff2 in `web/fonts/`, latin subset, each with its OFL text.
- **Display:** Bricolage Grotesque (variable wght). h1 and the empty-state heading only.
- **Text:** Hanken Grotesk (variable wght). Everything readable.
- **Mono:** IBM Plex Mono 400 and 500. Scores, `[n]` chips, doc names, kickers, the product's own vocabulary: soundings. `font-variant-numeric: tabular-nums` on every score.

Scale (one ratio, 1.2 on phone, 1.25 on desktop): 0.8125 / 0.9375 / 1 / 1.25 / 1.6 rem, with `clamp()` on h1. Measure 62ch for answers. `text-wrap: balance` on headings, `pretty` on body. Body 16px minimum so iOS does not zoom the textarea.

## 5. Layout

4/8 spacing scale as tokens (`--s1` 4px to `--s6` 48px). Container 72rem. Desktop at 900px and up: chat column plus a 19rem "What it knows" panel on the land tint, panel sticky. Under 900px it is one column and the panel becomes a closed `<details>` under the chat. Phone budget: first load fits in about 1.6 screens at 390px (header, intro, six question buttons, composer). Composer is sticky at the bottom of the chat column so the log scrolls above it.

Section jobs: header (identity, mode badge, theme switch); log (the conversation, with empty state); composer (ask); panel (what the corpus contains); footer (what this is and the repo link). No two adjacent sections share a layout family.

## 6. Depth, elevation, shape

One radius: 6px for everything (buttons, inputs, source rows, badges), except the 2px confidence gauge (section 13). Chips and the ping are circles by nature. No shadows; separation is tint (`--water`, `--land`) and a 1px `--line` border. Dark mode lifts lighter upward: ground, water, then bright edges.

## 7. Components and states

- **Mode badge.** Mono text from `/api/health`. States: loading ("Checking server"), claude, ollama, extractive (full sentence), unreachable ("Server not reachable").
- **Suggestion buttons.** Six, 44px min height, send the question directly (the box is not filled).
- **Composer.** Label above the textarea, Enter sends, Shift+Enter adds a line, count appears from 400 of 500 characters. Button reads "Ask". Disabled with the text "Searching" while a request is open.
- **Exchange.** Question (mono kicker "You asked"), then the answer, then the sounding list.
- **Citation chip `[n]`.** A button built as an element, 44px hit area via padding, scrolls to and focuses source n, opens it, highlights it.
- **Soundings (signature, section 8).**
- **Loading.** One sonar ping plus the words "Searching the documents".
- **Not grounded.** The not-found answer in the answer slot, then the closest passages all under the line with the label "Below the line".
- **Errors.** One notice per API code showing the server's own message; 429 shows the seconds the server states; provider 5xx still renders the retrieved sources; fetch failure shows "Can't reach the server" with a reload hint.
- **Empty (what it knows).** If `/api/documents` fails the panel says it could not load the list and the chat still works.

## 8. Signature set piece: the soundings

Under each answer, an ordered list of retrieved passages, one row per source, in descending score.
- Row header: the `[n]` chip, `doc > section` in mono, the score as a mono tabular numeral (`0.712`), and one of the words "Used" or "Below the line".
- Gauge: a bar from 0 to the score on a 0..1 scale, and a vertical **confidence line** at the API threshold (a dashed `--depth` contour with the threshold value printed once in the list caption). A bar that reaches past the line is brand coloured and the row stands out (brand-ink left rule, full-strength text). A bar short of the line is `--depth`, the row text is `--ink-muted` and sits dimmed under the line. Dimming uses a muted token, never opacity, so contrast holds.
- The passage text lives in a `<details>` body inside the row, closed by default.
- Interaction: clicking `[n]` in the answer opens row n, scrolls it into view (smooth only when motion is allowed), moves focus to its summary and adds a highlight outline for 1.6 seconds (a static outline, no animation).
- JS off: the page needs JS for chat anyway, so there is no static form of an answer; the `<noscript>` line says so.
- Reduced motion: no ping animation (a static ring and the same words), no smooth scroll, no transition delays.
- Anti-template check: nothing here reads as a chat skin; the line and numerals are what a surveyor would recognise.

## 9. Imagery

No photography, no illustrations, no generated imagery. The only graphic is `favicon.svg` (a ping ring and a dot, simple geometry). The ping animation is CSS borders.

## 10. Voice

Plain, first-person-free product copy in sentence case. Words used in the UI: passage, source, confidence line, the documents. "Sounding" stays in this file. No exclamation marks, no em dash, no banned vocabulary (DESIGN-CRAFT section 11). Hana is always described as fictional in the empty state and the footer. Audience-fit pass: no "chunk", "embedding", "top-k" in visible UI strings except the mode badge's model name.

## 11. Numeric constraints enforced by tests

- Every declared text/surface pair in both themes passes AA with margin (`tests/test_contrast.py`).
- Hex colours appear only inside token blocks in `styles.css` (the same test).
- No inline script bodies, `style=` attributes, `on*=` handlers, remote asset URLs (only the GitHub link), missing local assets, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` in `app.js`; every font family has its licence (`tests/test_web_static.py`).
- One radius token (plus the 2px gauge exception in section 13). One accent. Eyebrow-style uppercase labels: zero.

## 12. Responsive behaviour

Breakpoints: 900px (panel moves beside the chat). Touch targets 44px. At 390px no horizontal scroll: long doc names wrap with `overflow-wrap: anywhere`. Suggestions stack one per row under 520px. The mode badge wraps under the title on phones.

## 13. Decision log

- 2026-11-16. Scaled DESIGN-PROCESS for a one-page demo: references limited to two local design-md files plus the chart idiom; no live gallery screenshots; no artboards in a canvas tool, the HTML build was the artboard; the critique ran on build screenshots (below).
- 2026-11-16. Fonts: Bricolage Grotesque, Hanken Grotesk, IBM Plex Mono, all OFL from fontsource via jsdelivr, latin subset, checked in.
- 2026-11-16. Theme: system preference by default, manual toggle stored in localStorage inside try/catch, applied by a small blocking `theme.js` in the head to prevent a flash. This is an addition to the contract file list and is within `web/**`.
- 2026-11-16. Radius exception: the confidence gauge track and bar use 2px, not `--radius`, because a 6px radius on a 6px-high bar reads as a pill. It is the only exception.
- 2026-11-16. Gauge scale is 0 to 1, not rescaled to the observed range, so a bar is an honest score. The cost is short bars for typical scores; accepted.
- 2026-11-16. The skill rule against filled background tracks was weighed: the track here is the unfilled scale with the confidence line on it, which is the product's verb, so a faint track is kept.

## 14. Critique of the first build (DESIGN-PROCESS section 5, run on the 1440 and 390 screenshots)

Five things that could read as generated:
1. Six filled, identical suggestion cards in a two-column grid (the template tile grid). Fixed: an open list with hairline rows and a mono "Ask" cue, no fills.
2. Phone header wrapped into a stray toggle on its own line under the title. Fixed: brand and theme toggle share the first row, the mode badge takes the second.
3. The composer was sticky from first paint, so on a phone it ate a third of the empty state. Fixed: sticky only once the log has an exchange.
4. The intro heading ("Ask about Hana, then check the sources") read as a slogan and the footer was one dense paragraph. Fixed: plain statement of the verb as the heading, footer split into what it is and the fiction plus repo line.
5. The empty state shows no hint of the signature (soundings appear only after an answer). Not fixed: showing an example row would be invented data; the intro sentence names the confidence line instead. Recorded as accepted.
Also removed: nothing decorative was added; the only accessory removed was a filled card style on suggestions.

## 15. Visual QA pass on the real build (2026-11-16)

Reviewed with live Ollama answers at 390, 768, 1024 and 1440, light and dark, then AccessLint (`audit_live`) on the answered page and a keyboard-only run. Where the build loses to the two references: ollama keeps one narrow reading column, while ours let the sources run to the full column width (long bars, a ragged edge against the 62ch answer). Fixes, all in `web/`:
- Chat column capped at 42rem (log and composer), so answer, sources and composer share one edge.
- Space added between the answer and the sources heading; the "Used" and "Below the line" state moved onto the first row of each source (a source row dropped from about 93px to 65px on desktop). On phones the state sits beside the score on the second row.
- Sources heading is now an h2 (it followed the h1 directly once the intro hid, a skipped level) and each sources region is labelled "Sources for answer N" so landmarks are unique.
- Phone: the sticky composer shed its label (kept for screen readers) and the keyboard hint, and the textarea no longer takes focus after an answer on a coarse pointer, which had opened the keyboard over the sources. The composer went from about 160px to 85px of an 844px screen.
- A failed model call used to show "Nothing reached the confidence line" with sources marked Used. It now says the search worked, no answer was written, and reads the real threshold from `/api/health`.
- Placeholder added to the textarea, coloured with the muted ink token (AA).
Accepted: AAA enhanced contrast reports 6.0 to 6.9:1 on muted text (AA is met everywhere); the README shots cannot show two full exchanges in 900px, so the second answer is shown with the tail of the first above it.
