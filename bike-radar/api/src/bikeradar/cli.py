"""Command line: `bikeradar import <file|dir>`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from bikeradar.config import get_settings
from bikeradar.db import session_factory
from bikeradar.ingest.service import ImportResult, ImportStatus, import_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bikeradar", description="Bike Radar Danger Map")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="import MBT per-ride CSV exports (a file or a directory)")
    imp.add_argument("path", type=Path)
    imp.add_argument(
        "--replace",
        action="store_true",
        help="overwrite an existing ride with the same start, end and pass count",
    )
    imp.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args(argv)

    with session_factory()() as session:
        results = import_path(
            session,
            args.path,
            replace=args.replace,
            thresholds=get_settings().quality_thresholds(),
        )
    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        for r in results:
            print(_describe(r))
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        print("summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 1 if any(r.status == ImportStatus.FAILED for r in results) else 0


def _describe(r: ImportResult) -> str:
    line = f"{r.status:<18} {r.filename}"
    if r.ride_id is not None:
        line += f"  ride {r.ride_id}, {r.n_passes} passes"
    if r.flags_summary:
        line += "  flags " + ", ".join(f"{k}={v}" for k, v in r.flags_summary.items())
    if r.error:
        line += f"  ({r.error})"
    return line


if __name__ == "__main__":
    sys.exit(main())
