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
        "What does the Toronto zoning bylaw say about modular units?,,,no\n")
    s = evaluate(idx, qs, tmp_path / "out.csv")
    assert s["questions"] == 3
    assert s["hit@1"] == 1.0 and s["page_hit@5"] == 1.0 and s["mrr"] == 1.0
    assert s["refusal_rate"] == 1.0
    assert (tmp_path / "out.csv").exists()


def test_powerbi_workbook_has_one_table_per_sheet(corpus):
    from openpyxl import load_workbook
    from ckb.powerbi import export_workbook
    build(corpus, verbose=False)
    (corpus / "eval").mkdir()
    (corpus / "eval" / "questions.csv").write_text(
        "question,expected_doc_id,expected_page,answerable\n"
        "Where must thermal insulation be installed?,code-test,2,yes\n"
        "What does the Toronto zoning bylaw say about modular units?,,,no\n")
    (corpus / "exports").mkdir(exist_ok=True)
    con = connect(corpus / "data" / "ckb.duckdb")
    out = corpus / "exports" / "ckb_powerbi.xlsx"
    sheets = export_workbook(con, corpus, out)
    wb = load_workbook(out)
    assert wb.sheetnames == sheets
    assert all(list(wb[s].tables) == [s] for s in sheets)          # each sheet holds one named table
    versions = [r for r in wb["EvalVersions"].iter_rows(min_row=2, values_only=True)]
    assert versions[0][6] == 0.0 and versions[1][6] == 1.0          # refusal: baseline vs coverage check
