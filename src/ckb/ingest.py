"""Turn PDFs into page-aware chunks that keep their citation (document, page, section)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

# Code-style article numbers, e.g. "9.10.14.5." or "3.2.4.1." at the start of a line
DOT_LEADER_RE = re.compile(r"(?:\.\s?){6,}")   # "2.2.1 Productivity ........ 15"
MIN_ALNUM_CHARS = 25                           # drop leftover fragments like "s. 9"
SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,4})\.?\s+([A-Z][^\n]{0,80})", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    page: int            # 1-based page number, as a reader would cite it
    section: str | None  # nearest code article/section heading seen so far
    text: str


def extract_pages(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    return strip_boilerplate([clean(p.extract_text() or "") for p in reader.pages])


def strip_boilerplate(pages: list[str], min_share: float = 0.2, min_pages: int = 10) -> list[str]:
    """Drop running headers/footers: lines that repeat on at least min_share of pages.

    Example: the NBC prints a bilingual copyright line on every page; left in, it would sit in
    every chunk and match every query about "Canada" or "National Research Council".
    Page numbers are normalised to '#' first so "Division B 9-41" and "9-42" count as the same line.
    """
    if len(pages) < min_pages:
        return pages
    norm = lambda line: re.sub(r"\d+", "#", line.strip())
    counts: dict[str, int] = {}
    for page in pages:
        for line in {norm(l) for l in page.splitlines() if l.strip()}:
            counts[line] = counts.get(line, 0) + 1
    threshold = max(3, int(len(pages) * min_share))
    repeated = {line for line, n in counts.items() if n >= threshold}
    return ["\n".join(l for l in page.splitlines() if norm(l) not in repeated).strip() for page in pages]


def clean(text: str) -> str:
    text = text.replace("­", "")                 # soft hyphens
    text = re.sub(r"-\n(?=[a-z])", "", text)          # words split across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(l for l in text.splitlines() if not DOT_LEADER_RE.search(l))   # table-of-contents lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(doc_id: str, pages: list[str], max_chars: int = 900, overlap: int = 150) -> list[Chunk]:
    """Split each page into ~max_chars pieces on paragraph boundaries.

    Chunks never cross a page, so every chunk has exactly one page to cite.
    The current section heading carries forward across pages.
    """
    chunks: list[Chunk] = []
    section: str | None = None
    for page_no, text in enumerate(pages, start=1):
        if not text:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\d+(?:\.\d+)+\.?\s)", text) if p.strip()]
        buf = ""
        buf_section = section
        for para in paras:
            m = SECTION_RE.match(para)
            if m:
                section = f"{m.group(1)} {m.group(2).strip().rstrip(' .')}"
            if buf and len(buf) + len(para) + 1 > max_chars:
                if _keep(buf):
                    chunks.append(_make(doc_id, page_no, buf_section, buf, len(chunks)))
                buf = buf[-overlap:] + "\n" + para if overlap else para
                buf_section = section
            else:
                buf = f"{buf}\n{para}" if buf else para
                if buf_section is None:
                    buf_section = section
        if buf and _keep(buf):
            chunks.append(_make(doc_id, page_no, buf_section, buf, len(chunks)))
    return chunks


def _keep(chunk_text: str) -> bool:
    return len(re.sub(r"[^A-Za-z0-9]", "", chunk_text)) >= MIN_ALNUM_CHARS


def _make(doc_id: str, page: int, section: str | None, text: str, n: int) -> Chunk:
    return Chunk(chunk_id=f"{doc_id}-{n:05d}", doc_id=doc_id, page=page, section=section, text=text.strip())
