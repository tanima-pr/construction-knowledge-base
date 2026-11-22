"""One Excel workbook for the Power BI report: every table formatted as an Excel table.

The Power BI web service imports Excel tables (not plain ranges), so each dataset gets its own
sheet holding one named table. Evaluation tables are recomputed here, not copied from earlier
runs, so the workbook always matches the current code and question set.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .answer import MIN_COVERAGE
from .evaluate import evaluate
from .search import BM25Index
from .store import search_rows

THRESHOLDS = [0.0, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]


def _rows(con, sql: str) -> tuple[list[str], list[tuple]]:
    cur = con.execute(sql)
    return [d[0] for d in cur.description], cur.fetchall()


def _has_table(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0])


def _add_sheet(wb: Workbook, name: str, header: list[str], rows: list[tuple]) -> None:
    ws = wb.create_sheet(name)
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    for cell in ws[1]:
        cell.font = Font(name="Arial", bold=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial")
    last_row = max(len(rows) + 1, 2)            # an Excel table needs at least one data row
    ref = f"A1:{get_column_letter(len(header))}{last_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    for i, col in enumerate(header, start=1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:200] if r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "A2"


def export_workbook(con, root: Path, out_path: Path) -> list[str]:
    wb = Workbook()
    wb.remove(wb.active)
    added = []

    for name, sql in [
        ("Catalog", "SELECT doc_id, title, issuer, doc_type, edition, published, licence, access_level, "
                    "local_file, sha256, status, problems, checked_at FROM catalog ORDER BY doc_id"),
        ("Coverage", """SELECT k.doc_id, k.title, k.doc_type, k.status, count(c.chunk_id) AS chunks,
                        count(DISTINCT c.page) AS pages_with_text, count(DISTINCT c.section) AS sections
                        FROM catalog k LEFT JOIN chunks c USING (doc_id) GROUP BY ALL ORDER BY k.doc_id"""),
    ]:
        header, rows = _rows(con, sql)
        _add_sheet(wb, name, header, rows)
        added.append(name)

    questions = root / "eval" / "questions.csv"
    if questions.exists():
        index = BM25Index(search_rows(con))
        tmp = root / "exports" / "_eval_tmp.csv"
        versions = [("Baseline (score cut-off only)", 0.0), (f"Coverage check {MIN_COVERAGE}", MIN_COVERAGE)]
        vrows = []
        for label, t in versions:
            s = evaluate(index, questions, tmp if t == MIN_COVERAGE else None, min_coverage=t)
            vrows.append((label, s["questions"], s["hit@1"], s["hit@5"], s["page_hit@5"], s["mrr"],
                          s["refusal_rate"], s["false_refusal"]))
        _add_sheet(wb, "EvalVersions", ["version", "questions", "hit_at_1", "hit_at_5", "page_hit_at_5",
                                        "mrr", "refusal_rate", "false_refusal"], vrows)
        sweep = []
        for t in THRESHOLDS:
            s = evaluate(index, questions, None, min_coverage=t)
            sweep.append((t, s["refusal_rate"], s["false_refusal"]))
        _add_sheet(wb, "ThresholdSweep", ["threshold", "refusal_rate", "false_refusal"], sweep)

        import csv
        with open(tmp, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [tuple(r[h] for h in header) for r in reader]
        tmp.unlink()
        _add_sheet(wb, "EvalResults", header, rows)
        added += ["EvalVersions", "ThresholdSweep", "EvalResults"]

    if _has_table(con, "ifc_elements"):
        for name, sql in [("IfcSummary", "SELECT * FROM ifc_summary"), ("IfcQuality", "SELECT * FROM ifc_quality")]:
            header, rows = _rows(con, sql)
            _add_sheet(wb, name, header, rows)
            added.append(name)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return added
