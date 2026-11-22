"""Fixtures: a tiny corpus of generated PDFs and a register, so tests never need the real documents."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DOCS = {
    "code-test": [
        "9.10.14.5. Construction of Exposing Building Face\nThe exposing building face shall have a fire-resistance rating "
        "where the limiting distance is less than the prescribed value.",
        "9.25.2.1. Required Insulation\nThermal insulation shall be installed in walls, ceilings and floors that "
        "separate heated space from unheated space.",
    ],
    "roadmap-test": [
        "Industrialized construction moves work from the site into a factory. Volumetric modular units are built "
        "as complete rooms and craned into place.",
        "Panelized systems ship wall and floor panels to site. A productivity data framework would capture data and "
        "measure the impact of offsite construction.",
    ],
    "notes-internal": [
        "Interview notes: the hiring team asked about retention schedules and Protected B handling.",
    ],
}

REGISTER = """doc_id,title,issuer,doc_type,edition,published,source_url,licence,access_level,local_file
code-test,Test Building Code,Test Issuer,code,2020,2022-03-28,https://example.org/code,test,public,code-test.pdf
roadmap-test,Test IC Roadmap,Test Issuer,report,,2025-04-01,https://example.org/roadmap,test,public,roadmap-test.pdf
notes-internal,Internal Notes,Me,notes,,2026-11-22,local,private,internal,notes-internal.pdf
"""


def write_pdf(path: Path, pages: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for page in pages:
        y = 740
        for para in page.split("\n"):
            words, line = para.split(), ""
            for w in words:
                if len(line) + len(w) > 90:
                    c.drawString(60, y, line)
                    y -= 14
                    line = ""
                line = f"{line} {w}".strip()
            c.drawString(60, y, line)
            y -= 28
        c.showPage()
    c.save()


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "sources" / "register.csv").write_text(REGISTER)
    for doc_id, pages in DOCS.items():
        write_pdf(tmp_path / "data" / "raw" / f"{doc_id}.pdf", pages)
    return tmp_path
