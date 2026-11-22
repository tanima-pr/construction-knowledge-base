# Construction Knowledge Base

Governed search over Canadian construction documents: the National Building Code of Canada 2025, NRC's
industrialized-construction roadmap and related guides. Every answer cites document and page, and every
document is tracked in a source register with a checksum and an access level. A second module reads BIM
models (IFC) into the same DuckDB database.

**Why:** construction knowledge lives in long, unstructured PDFs and BIM models, not tables. This project
shows the information-management side of the problem: knowing what you hold, where it came from, whether
it changed, who may see it, and how well the search actually works.

## What it does

| Step | What happens | Governance point |
|---|---|---|
| Register | `sources/register.csv` lists each document: issuer, type, edition, published date, source URL, licence, access level | Required fields are validated; bad rows are marked `invalid` |
| Fingerprint | SHA-256 of every PDF on each build | A replaced file is flagged `changed` and re-ingested; unchanged files are skipped |
| Ingest | Text extracted page by page, split on paragraph boundaries, never across pages | Each chunk keeps its page and the nearest code article (e.g. `9.10.14.5`) |
| Search | BM25 keyword ranking, filtered by access level | `internal` documents are hidden unless explicitly requested |
| Answer | Top passages with `[doc p.N, section]` citations, or "Not found" below a score threshold | Optional LLM hook only sees retrieved passages; uncited model answers are discarded |
| Evaluate | Hand-checked question set → hit@1, hit@5, page hit@5, MRR, refusal rate | Search quality is measured, not assumed |
| IFC | IfcOpenShell reads walls, slabs, etc. with storey, type, material and quantities | Same database, so documents and model data sit side by side |
| Export | `exports/*.csv` (catalog health, coverage, eval results, IFC summary) | Ready for a Power BI report |

## Quick start

```bash
pip install -r requirements.txt
pytest -q                      # 11 tests on generated PDFs and a generated IFC model

# 1. Download the PDFs listed in sources/register.csv into data/raw/ (names must match local_file)
# 2. Fill any blank required fields (the build tells you which)
PYTHONPATH=src python -m ckb build
PYTHONPATH=src python -m ckb ask "What does industrialized construction mean?"
PYTHONPATH=src python -m ckb eval                       # after writing eval/questions.csv
PYTHONPATH=src python -m ckb ifc data/raw/<model>.ifc   # any IFC2x3/IFC4 sample model
```

Sample IFC models: [buildingSMART Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files),
[IfcOpenShell test files](https://github.com/IfcOpenShell/files).

Source PDFs and models are **not committed** (see `.gitignore`); the register records where to get each one.

## Layout

```
sources/register.csv     source register (hand-maintained)
eval/questions.csv       hand-checked question set
src/ckb/catalog.py       register validation + SHA-256 change detection
src/ckb/ingest.py        PDF text extraction and page-aware chunking
src/ckb/search.py        BM25 ranking with access-level filter
src/ckb/answer.py        cited answers, refusal, LLM guardrail
src/ckb/evaluate.py      retrieval metrics
src/ckb/ifc_extract.py   IFC elements and quantities -> DuckDB
src/ckb/pipeline.py      build + CSV exports
tests/                   pytest suite (runs in GitHub Actions)
```

## Results

_Fill in after running on the real documents:_

| Documents | Pages | Chunks | Questions | hit@1 | hit@5 | Page hit@5 | Refusal rate |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## Limitations

- Keyword search: misses questions phrased very differently from the code text. Embedding search is the natural next step, and the eval set shows whether it helps.
- Tables and figures in the PDFs extract poorly; answers about values in tables should be checked against the page cited.
- The register's access levels demonstrate the control; they are not a security boundary.
