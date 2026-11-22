from pathlib import Path

from ckb.evaluate import evaluate
from ckb.pipeline import build
from ckb.search import BM25Index
from ckb.store import connect, search_rows


def test_evaluate_scores_questions(corpus, tmp_path):
    build(corpus, verbose=False)
    con = connect(corpus / "data" / "ckb.duckdb")
    idx = BM25Index(search_rows(con))
    qs = tmp_path / "q.csv"
    qs.write_text(
        "question,expected_doc_id,expected_page,answerable\n"
        "Where must thermal insulation be installed?,code-test,2,yes\n"
        "What is volumetric modular construction?,roadmap-test,1,yes\n"
        "What is the minister's salary?,,,no\n")
    s = evaluate(idx, qs, tmp_path / "out.csv")
    assert s["questions"] == 3
    assert s["hit@1"] == 1.0 and s["page_hit@5"] == 1.0 and s["mrr"] == 1.0
    assert s["refusal_rate"] == 1.0
    assert (tmp_path / "out.csv").exists()
