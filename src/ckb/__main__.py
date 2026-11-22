"""Command line:

  python -m ckb build                     validate register, ingest new/changed PDFs, export CSVs
  python -m ckb ask "question" [--internal]
  python -m ckb eval                      score retrieval on eval/questions.csv
  python -m ckb ifc path/to/model.ifc     load a BIM model into DuckDB and export ifc_summary.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .answer import answer
from .evaluate import evaluate
from .pipeline import build
from .search import BM25Index
from .store import connect, search_rows

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "ckb.duckdb"


def main() -> None:
    p = argparse.ArgumentParser(prog="ckb")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--internal", action="store_true", help="also search documents marked internal")
    a.add_argument("-k", type=int, default=5)
    sub.add_parser("eval")
    i = sub.add_parser("ifc")
    i.add_argument("path", type=Path)
    args = p.parse_args()

    if args.cmd == "build":
        build(ROOT, DB)
        return

    con = connect(DB)
    if args.cmd == "ifc":
        from .ifc_extract import load
        print(load(con, args.path))
        out = ROOT / "exports"
        out.mkdir(exist_ok=True)
        con.execute(f"COPY (SELECT * FROM ifc_summary) TO '{out / 'ifc_summary.csv'}' (HEADER)")
        print(con.execute("SELECT * FROM ifc_summary").df().to_string(index=False))
        return

    index = BM25Index(search_rows(con))
    if args.cmd == "ask":
        access = {"public", "internal"} if args.internal else {"public"}
        result = answer(args.question, index.search(args.question, k=args.k, allowed_access=access))
        print(result["answer"])
        print("\nSources:", json.dumps(result["citations"], indent=2))
    elif args.cmd == "eval":
        summary = evaluate(index, ROOT / "eval" / "questions.csv", ROOT / "exports" / "eval_results.csv")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
