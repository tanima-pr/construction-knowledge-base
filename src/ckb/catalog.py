"""Source register: what documents we hold, where they came from, and whether they changed.

The register (sources/register.csv) is maintained by hand. Every build checks it:
required fields present, access level valid, local file present, and a SHA-256
fingerprint so a silently replaced PDF is detected on the next build.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ["doc_id", "title", "issuer", "doc_type", "published", "source_url", "access_level", "local_file"]
ACCESS_LEVELS = {"public", "internal"}


@dataclass
class Source:
    doc_id: str
    title: str
    issuer: str
    doc_type: str
    edition: str
    published: str
    source_url: str
    licence: str
    access_level: str
    local_file: str
    sha256: str | None = None
    status: str = "pending"          # ok | missing_file | changed | invalid
    problems: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_register(register_csv: Path, raw_dir: Path, previous: dict[str, str] | None = None) -> list[Source]:
    """Read the register and validate each row.

    previous: doc_id -> sha256 from the last build, used to flag changed files.
    """
    previous = previous or {}
    sources: list[Source] = []
    seen: set[str] = set()
    with open(register_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k: (v or "").strip() for k, v in row.items()}
            if not row.get("doc_id") or row["doc_id"].startswith("#"):
                continue
            src = Source(**{k: row.get(k, "") for k in Source.__dataclass_fields__ if k not in {"sha256", "status", "problems"}})
            for col in REQUIRED:
                if not getattr(src, col):
                    src.problems.append(f"missing {col}")
            if src.access_level and src.access_level not in ACCESS_LEVELS:
                src.problems.append(f"access_level must be one of {sorted(ACCESS_LEVELS)}")
            if src.doc_id in seen:
                src.problems.append("duplicate doc_id")
            seen.add(src.doc_id)

            path = raw_dir / src.local_file if src.local_file else None
            if src.problems:
                src.status = "invalid"
            elif path is None or not path.exists():
                src.status = "missing_file"
            else:
                src.sha256 = sha256_of(path)
                old = previous.get(src.doc_id)
                src.status = "changed" if old and old != src.sha256 else "ok"
            sources.append(src)
    return sources


def catalog_rows(sources: list[Source]) -> list[tuple]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [
        (s.doc_id, s.title, s.issuer, s.doc_type, s.edition, s.published, s.source_url,
         s.licence, s.access_level, s.local_file, s.sha256, s.status, "; ".join(s.problems), now)
        for s in sources
    ]
