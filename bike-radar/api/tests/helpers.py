"""Builders for MBT CSV test inputs derived from the synthetic fixture."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "mbt_export_synthetic.csv"


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def fixture_rows() -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(FIXTURE.read_text())))
    return rows[0], rows[1:]


def build_csv(
    header: list[str] | None = None,
    rows: list[list[str]] | None = None,
    overrides: Mapping[int, Mapping[str, str]] | None = None,
) -> bytes:
    """Fixture CSV with optional header/rows replaced and per-car cell overrides."""
    base_header, base_rows = fixture_rows()
    header = base_header if header is None else header
    rows = [list(r) for r in (base_rows if rows is None else rows)]
    for row in rows:
        for col, value in (overrides or {}).get(int(row[0]), {}).items():
            row[base_header.index(col)] = value
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()
