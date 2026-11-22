from pathlib import Path

from ckb.answer import NOT_FOUND, answer
from ckb.catalog import load_register
from ckb.ingest import chunk_pages
from ckb.pipeline import build
from ckb.search import BM25Index
from ckb.store import connect, search_rows


def _index(root: Path) -> BM25Index:
    con = connect(root / "data" / "ckb.duckdb")
    rows = search_rows(con)
    con.close()
    return BM25Index(rows)


# ---- register / governance -------------------------------------------------

def test_register_flags_missing_fields_and_files(corpus):
    reg = corpus / "sources" / "register.csv"
    reg.write_text(reg.read_text() + "bad-row,,Issuer,report,,2024,https://x,,secret,nope.pdf\n"
                   "ghost,Ghost Doc,Issuer,report,,2024,https://x,,public,ghost.pdf\n")
    by_id = {s.doc_id: s for s in load_register(reg, corpus / "data" / "raw")}
    assert by_id["bad-row"].status == "invalid"
    assert "missing title" in by_id["bad-row"].problems
    assert any("access_level" in p for p in by_id["bad-row"].problems)
    assert by_id["ghost"].status == "missing_file"
    assert by_id["code-test"].status == "ok" and len(by_id["code-test"].sha256) == 64


def test_changed_file_is_detected_and_reingested(corpus):
    first = build(corpus, verbose=False)
    assert sorted(first["ingested"]) == ["code-test", "notes-internal", "roadmap-test"]
    assert build(corpus, verbose=False)["ingested"] == []          # nothing changed

    pdf = corpus / "data" / "raw" / "roadmap-test.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"\n%touched")
    third = build(corpus, verbose=False)
    assert third["ingested"] == ["roadmap-test"]
    con = connect(corpus / "data" / "ckb.duckdb")
    assert con.execute("SELECT status FROM catalog WHERE doc_id='roadmap-test'").fetchone()[0] == "changed"


def test_exports_written(corpus):
    build(corpus, verbose=False)
    assert (corpus / "exports" / "catalog.csv").exists()
    assert (corpus / "exports" / "coverage.csv").exists()


# ---- chunking -------------------------------------------------------------

def test_chunks_keep_page_and_section():
    pages = ["9.10.14.5. Construction of Exposing Building Face\nSome text.", "Continued requirements for exposing building faces."]
    chunks = chunk_pages("doc", pages)
    assert [c.page for c in chunks] == [1, 2]
    assert chunks[0].section.startswith("9.10.14.5")
    assert chunks[1].section == chunks[0].section       # heading carries forward


def test_long_page_is_split_without_crossing_pages():
    page = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_pages("doc", [page], max_chars=500)
    assert len(chunks) > 3 and all(c.page == 1 for c in chunks)


# ---- retrieval, access control, answers -----------------------------------

def test_search_ranks_the_right_document(corpus):
    build(corpus, verbose=False)
    idx = _index(corpus)
    assert idx.search("volumetric modular units craned")[0].doc_id == "roadmap-test"
    top = idx.search("thermal insulation heated space")[0]
    assert (top.doc_id, top.page) == ("code-test", 2)


def test_internal_documents_hidden_by_default(corpus):
    build(corpus, verbose=False)
    idx = _index(corpus)
    assert all(h.doc_id != "notes-internal" for h in idx.search("retention schedules Protected B"))
    assert idx.search("retention schedules Protected B", allowed_access={"public", "internal"})[0].doc_id == "notes-internal"


def test_answer_cites_or_refuses(corpus):
    build(corpus, verbose=False)
    idx = _index(corpus)
    good = answer("fire-resistance rating limiting distance", idx.search("fire-resistance rating limiting distance"))
    assert "[code-test p.1" in good["answer"] and good["citations"][0]["page"] == 1
    assert answer("salary of the minister", idx.search("salary of the minister"))["answer"] == NOT_FOUND


def test_llm_answer_without_citation_is_rejected(corpus):
    build(corpus, verbose=False)
    idx = _index(corpus)
    hits = idx.search("panelized wall panels")
    out = answer("panelized wall panels", hits, llm=lambda prompt: "Panels are shipped to site.")
    assert out["answer"].startswith(NOT_FOUND)
    out = answer("panelized wall panels", hits, llm=lambda prompt: "Panels ship to site [roadmap-test p.2].")
    assert "[roadmap-test p.2]" in out["answer"]


def test_running_header_and_footer_are_stripped():
    from ckb.ingest import strip_boilerplate
    topics = ["stairs", "guards", "ramps", "doors", "windows", "insulation", "fire walls", "sprinklers", "roofs",
              "chimneys", "decks", "foundations", "framing", "plumbing", "egress", "ventilation", "radon", "noise",
              "accessibility", "garages"]
    pages = [f"Division B 9-{i}\nRequirements for {t} in small buildings.\n© Copyright line" for i, t in enumerate(topics)]
    out = strip_boilerplate(pages)
    assert all("Copyright" not in p and "Division B" not in p for p in out)
    assert out[3] == "Requirements for doors in small buildings."


def test_table_of_contents_and_fragments_dropped():
    from ckb.ingest import clean
    toc = "2.2 Drivers of IC adoption ........................ 14\n2.2.1 Productivity ............ 15"
    assert clean(toc) == ""
    chunks = chunk_pages("doc", ["s. 9", "A real paragraph about volumetric modular construction in factories."])
    assert [c.page for c in chunks] == [2]


def test_refuses_when_question_words_are_missing(corpus):
    build(corpus, verbose=False)
    idx = _index(corpus)
    # shares "modular" with the corpus, but "toronto", "zoning", "bylaw" never appear
    q = "What does the Toronto zoning bylaw say about modular units?"
    hits = idx.search(q)
    assert hits and hits[0].score > 0                   # BM25 alone would answer
    assert answer(q, hits)["answer"] == NOT_FOUND        # coverage check refuses
    q2 = "Where must thermal insulation be installed?"
    assert answer(q2, idx.search(q2))["answer"] != NOT_FOUND
