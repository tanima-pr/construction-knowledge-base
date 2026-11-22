"""Measure retrieval quality against a hand-written question set.

eval/questions.csv columns:
  question, expected_doc_id, expected_page (optional), answerable (yes/no)

Metrics:
  hit@1, hit@5   - right document in the top 1 / top 5 results
  page_hit@5     - right document AND page in the top 5 (when a page is given)
  mrr            - mean reciprocal rank of the first correct document
  refusal_rate   - for answerable=no questions, how often we correctly say "not found"
"""
from __future__ import annotations

import csv
from pathlib import Path

from .answer import NOT_FOUND, answer
from .search import BM25Index


def evaluate(index: BM25Index, questions_csv: Path, out_csv: Path | None = None, k: int = 5,
             min_score: float = 1.0) -> dict:
    rows, answerable, unanswerable = [], [], []
    with open(questions_csv, newline="", encoding="utf-8") as f:
        for q in csv.DictReader(f):
            if not q.get("question") or q["question"].startswith("#"):
                continue
            hits = index.search(q["question"], k=k)
            ranked_docs = [h.doc_id for h in hits]
            exp_doc, exp_page = q.get("expected_doc_id", "").strip(), q.get("expected_page", "").strip()
            is_answerable = q.get("answerable", "yes").strip().lower() != "no"
            rank = ranked_docs.index(exp_doc) + 1 if exp_doc in ranked_docs else None
            page_hit = None
            if exp_page:
                page_hit = any(h.doc_id == exp_doc and str(h.page) == exp_page for h in hits)
            refused = answer(q["question"], hits, min_score=min_score)["answer"] == NOT_FOUND
            row = {"question": q["question"], "expected_doc_id": exp_doc, "expected_page": exp_page,
                   "answerable": "yes" if is_answerable else "no", "rank": rank or "",
                   "top_doc": ranked_docs[0] if ranked_docs else "", "top_page": hits[0].page if hits else "",
                   "page_hit": "" if page_hit is None else page_hit, "refused": refused}
            rows.append(row)
            (answerable if is_answerable else unanswerable).append(row)

    n = len(answerable) or 1
    paged = [r for r in answerable if r["page_hit"] != ""]
    summary = {
        "questions": len(rows),
        "hit@1": round(sum(1 for r in answerable if r["rank"] == 1) / n, 3),
        f"hit@{k}": round(sum(1 for r in answerable if r["rank"]) / n, 3),
        f"page_hit@{k}": round(sum(1 for r in paged if r["page_hit"]) / len(paged), 3) if paged else None,
        "mrr": round(sum(1 / r["rank"] for r in answerable if r["rank"]) / n, 3),
        "refusal_rate": round(sum(1 for r in unanswerable if r["refused"]) / len(unanswerable), 3) if unanswerable else None,
    }
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["question"])
            w.writeheader()
            w.writerows(rows)
    return summary
