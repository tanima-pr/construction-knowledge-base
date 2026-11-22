"""BM25 keyword search over chunks, with access-level filtering.

Plain Python on purpose: no external search service, easy to explain, and the
same ranking runs on a laptop or in CI.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this to was were will with
which what when where who how shall must may be been not no any all each per than then there their these those""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    page: int
    section: str | None
    text: str
    score: float
    coverage: float = 0.0   # share of the query's IDF weight found in this chunk (0-1)


class BM25Index:
    def __init__(self, rows: list[dict], k1: float = 1.5, b: float = 0.75):
        """rows: dicts with chunk_id, doc_id, title, page, section, text, access_level."""
        self.rows = rows
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(r["text"] + " " + (r.get("section") or "") + " " + r["title"])) for r in rows]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = (sum(self.lens) / len(self.lens)) if rows else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(rows)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        # a word the corpus never uses is maximally informative: missing it should hurt coverage most
        self.unseen_idf = math.log(1 + (n + 0.5) / 0.5) if rows else 0.0

    def coverage(self, query_terms: list[str], i: int) -> float:
        """IDF-weighted share of distinct query terms present in chunk i."""
        terms = set(query_terms)
        if not terms:
            return 0.0
        total = sum(self.idf.get(t, self.unseen_idf) for t in terms)
        found = sum(self.idf[t] for t in terms if t in self.tfs[i])
        return found / total

    def search(self, query: str, k: int = 5, allowed_access: set[str] | None = None) -> list[Hit]:
        allowed_access = allowed_access or {"public"}
        q = tokenize(query)
        scored = []
        for i, r in enumerate(self.rows):
            if r.get("access_level", "public") not in allowed_access:
                continue
            tf, dl = self.tfs[i], self.lens[i]
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_len))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [
            Hit(r["chunk_id"], r["doc_id"], r["title"], r["page"], r.get("section"), r["text"], round(s, 3),
                round(self.coverage(q, i), 3))
            for s, i in scored[:k]
            for r in [self.rows[i]]
        ]
