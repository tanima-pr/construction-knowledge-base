"""Build: validate the register, (re)ingest new or changed documents, export tables for Power BI."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .catalog import catalog_rows, load_register
from .ingest import chunk_pages, extract_pages
from .store import connect, previous_hashes


def build(root: Path, db_path: Path | None = None, verbose: bool = True) -> dict:
    db_path = db_path or root / "data" / "ckb.duckdb"
    raw_dir = root / "data" / "raw"
    con = connect(db_path)

    sources = load_register(root / "sources" / "register.csv", raw_dir, previous_hashes(con))
    con.execute("DELETE FROM catalog")
    con.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", catalog_rows(sources))

    last_ingested = dict(con.execute(
        "SELECT doc_id, arg_max(sha256, ingested_at) FROM ingest_log GROUP BY doc_id").fetchall())
    summary = {"ingested": [], "skipped_unchanged": [], "missing_file": [], "invalid": []}

    for s in sources:
        if s.status in ("missing_file", "invalid"):
            summary[s.status].append(s.doc_id)
            con.execute("DELETE FROM chunks WHERE doc_id = ?", [s.doc_id])
            continue
        if last_ingested.get(s.doc_id) == s.sha256:
            summary["skipped_unchanged"].append(s.doc_id)
            continue
        pages = extract_pages(raw_dir / s.local_file)
        chunks = chunk_pages(s.doc_id, pages)
        con.execute("DELETE FROM chunks WHERE doc_id = ?", [s.doc_id])
        con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                        [(c.chunk_id, c.doc_id, c.page, c.section, c.text, len(c.text)) for c in chunks])
        con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?,?)",
                    [s.doc_id, s.sha256, len(pages), sum(1 for p in pages if not p), len(chunks),
                     datetime.now(timezone.utc).isoformat(timespec="seconds")])
        summary["ingested"].append(s.doc_id)

    export(con, root / "exports")
    if verbose:
        for k, v in summary.items():
            print(f"{k:>18}: {len(v)} {v if v else ''}")
    con.close()
    return summary


def export(con, out_dir: Path) -> None:
    """CSV extracts for the Power BI report (catalog health, coverage, eval results)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY catalog TO '{out_dir / 'catalog.csv'}' (HEADER)")
    con.execute(f"""COPY (
        SELECT k.doc_id, k.title, k.doc_type, k.access_level, k.status,
               count(c.chunk_id) AS chunks, count(DISTINCT c.page) AS pages_with_text,
               count(DISTINCT c.section) AS sections
        FROM catalog k LEFT JOIN chunks c USING (doc_id)
        GROUP BY ALL ORDER BY k.doc_id) TO '{out_dir / 'coverage.csv'}' (HEADER)""")
