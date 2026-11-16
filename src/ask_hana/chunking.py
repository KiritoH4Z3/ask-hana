"""Split markdown documents into overlapping, citable chunks. Pure functions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

CHUNKER_VERSION = "1"
WINDOW_WORDS = 180
OVERLAP_WORDS = 40

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass(frozen=True)
class Chunk:
    id: str
    doc: str
    title: str
    section: str
    position: int
    text: str

    @property
    def embed_text(self) -> str:
        return f"{self.title} > {self.section}\n{self.text}"

    @property
    def words(self) -> int:
        return len(self.text.split())


BOM = chr(0xFEFF)  # a Windows editor puts this before the first character


def chunk_id(doc: str, position: int, text: str) -> str:
    return hashlib.sha256(f"{doc}|{position}|{text}".encode()).hexdigest()[:16]


def _wc(text: str) -> int:
    return len(text.split())


def parse_sections(markdown: str, fallback_title: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (title, [(section, body)]). Text before the first `##` is the Overview."""
    markdown = markdown.lstrip(BOM)
    title = fallback_title
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    seen_title = False
    for line in markdown.splitlines():
        if not seen_title and line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip() or fallback_title
            seen_title = True
        elif line.startswith("## "):
            sections.append((line[3:].strip() or "Section", []))
        else:
            sections[-1][1].append(line)
    return title, [
        (name, "\n".join(body).strip()) for name, body in sections if "".join(body).strip()
    ]


def _sentences(body: str) -> list[tuple[str, str]]:
    """Split a body into (separator, sentence). Line breaks survive as "\n" separators."""
    out: list[tuple[str, str]] = []
    for line in body.splitlines():
        line = _BULLET.sub("", line).strip()
        if not line:
            continue
        for i, sentence in enumerate(_SENTENCE_END.split(line)):
            sentence = sentence.strip()
            if sentence:
                out.append(("\n" if i == 0 and out else " ", sentence))
    return out


def _split_long(sentence: str, limit: int) -> list[str]:
    words = sentence.split()
    return [" ".join(words[i : i + limit]) for i in range(0, len(words), limit)]


def _join(units: list[tuple[str, str]]) -> str:
    return "".join((sep if i else "") + s for i, (sep, s) in enumerate(units))


def window_section(body: str) -> list[str]:
    """Windows of about WINDOW_WORDS words, overlapping by about OVERLAP_WORDS."""
    units: list[tuple[str, str]] = []
    for sep, sentence in _sentences(body):
        if _wc(sentence) > WINDOW_WORDS:
            pieces = _split_long(sentence, WINDOW_WORDS)
            units.extend((sep if j == 0 else " ", p) for j, p in enumerate(pieces))
        else:
            units.append((sep, sentence))
    if not units:
        return []
    if sum(_wc(s) for _, s in units) <= WINDOW_WORDS:
        return [_join(units)]

    windows: list[str] = []
    start = 0
    while start < len(units):
        end, total = start, 0
        while end < len(units) and (end == start or total + _wc(units[end][1]) <= WINDOW_WORDS):
            total += _wc(units[end][1])
            end += 1
        windows.append(_join(units[start:end]))
        if end >= len(units):
            break
        # Step back over trailing sentences worth about OVERLAP_WORDS, always moving forward.
        back, carried = end, 0
        while back > start + 1 and carried < OVERLAP_WORDS:
            back -= 1
            carried += _wc(units[back][1])
        start = max(back, start + 1)
    return windows


def chunk_document(filename: str, markdown: str) -> list[Chunk]:
    title, sections = parse_sections(markdown, Path(filename).stem.replace("-", " ").title())
    chunks: list[Chunk] = []
    for section, body in sections:
        for text in window_section(body):
            text = text.strip()
            if text:
                position = len(chunks)
                chunks.append(
                    Chunk(
                        chunk_id(filename, position, text), filename, title, section, position, text
                    )
                )
    return chunks


def knowledge_files(knowledge_dir: Path) -> list[Path]:
    if not knowledge_dir.is_dir():
        return []
    return sorted(p for p in knowledge_dir.glob("*.md") if p.is_file())


def load_chunks(knowledge_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in knowledge_files(knowledge_dir):
        chunks.extend(chunk_document(path.name, path.read_text(encoding="utf-8-sig")))
    return chunks
