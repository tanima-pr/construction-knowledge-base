"""Answers that always say where they came from.

Default mode is extractive: return the best passages with citations, or say the
documents don't cover it. An LLM can be plugged in through `llm` — it only ever
sees the retrieved passages and must cite them, the same guardrail idea as the
eHospital assistant.
"""
from __future__ import annotations

from typing import Callable

from .search import Hit

NOT_FOUND = "Not found in the indexed documents."

PROMPT = """Answer the question using ONLY the passages below.
Cite every claim as [doc_id p.PAGE]. If the passages do not answer it, reply exactly: "{not_found}"

Question: {question}

Passages:
{passages}
"""


def cite(hit: Hit) -> str:
    sec = f", {hit.section}" if hit.section else ""
    return f"[{hit.doc_id} p.{hit.page}{sec}]"


MIN_COVERAGE = 0.45   # chosen on eval/questions.csv; see README "Refusal threshold"


def answer(question: str, hits: list[Hit], min_score: float = 1.0, min_coverage: float = MIN_COVERAGE,
           llm: Callable[[str], str] | None = None, max_passages: int = 3) -> dict:
    """Refuse unless some retrieved passage covers enough of the question's informative words.

    BM25 scores are not comparable across questions, so a score cut-off alone cannot tell
    "weak match" from "no match". Coverage asks a simpler question: does any passage contain
    most of what the question is about (weighted by how rare each word is)?
    """
    usable = [h for h in hits if h.score >= min_score][:max_passages]
    if not usable or max(h.coverage for h in usable) < min_coverage:
        return {"question": question, "answer": NOT_FOUND, "citations": []}

    citations = [{"doc_id": h.doc_id, "title": h.title, "page": h.page, "section": h.section, "score": h.score} for h in usable]
    if llm is None:
        body = "\n\n".join(f"{cite(h)}\n{snippet(h.text)}" for h in usable)
        return {"question": question, "answer": body, "citations": citations}

    passages = "\n\n".join(f"{cite(h)} {h.text}" for h in usable)
    reply = llm(PROMPT.format(not_found=NOT_FOUND, question=question, passages=passages)).strip()
    if reply != NOT_FOUND and "[" not in reply:   # guardrail: uncited answers are rejected
        reply = NOT_FOUND + " (model answer had no citations and was discarded)"
    return {"question": question, "answer": reply, "citations": citations}


def snippet(text: str, n: int = 400) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"
