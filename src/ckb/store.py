"""DuckDB layer: catalog, chunks, ingestion log, eval results, IFC tables."""
from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    doc_id VARCHAR PRIMARY KEY, title VARCHAR, issuer VARCHAR, doc_type VARCHAR, edition VARCHAR,
    published VARCHAR, source_url VARCHAR, licence VARCHAR, access_level VARCHAR, local_file VARCHAR,
    sha256 VARCHAR, status VARCHAR, problems VARCHAR, checked_at VARCHAR
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, page INTEGER, section VARCHAR, text VARCHAR, n_chars INTEGER
);
CREATE TABLE IF NOT EXISTS ingest_log (
    doc_id VARCHAR, sha256 VARCHAR, pages INTEGER, empty_pages INTEGER, chunks INTEGER, ingested_at VARCHAR
);
"""


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    return con


def previous_hashes(con) -> dict[str, str]:
    return {d: h for d, h in con.execute("SELECT doc_id, sha256 FROM catalog WHERE sha256 IS NOT NULL").fetchall()}


def search_rows(con) -> list[dict]:
    cols = ["chunk_id", "doc_id", "title", "page", "section", "text", "access_level"]
    q = """SELECT c.chunk_id, c.doc_id, k.title, c.page, c.section, c.text, k.access_level
           FROM chunks c JOIN catalog k USING (doc_id) WHERE k.status IN ('ok', 'changed')"""
    return [dict(zip(cols, r)) for r in con.execute(q).fetchall()]
