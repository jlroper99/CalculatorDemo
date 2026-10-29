"""Import MBT CSV rides into the database with file- and content-level dedupe (features/001)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bikeradar.ingest.mbt_csv import MbtCsvError, ParsedRide, QualityThresholds, parse, sha256
from bikeradar.models import Pass, Ride, RideSource

POSSIBLE_DUPLICATE_HINT = (
    "same start, end and pass count as an existing ride; use replace to overwrite"
)


class ImportStatus(StrEnum):
    IMPORTED = "imported"
    REPLACED = "replaced"
    DUPLICATE = "duplicate"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    FAILED = "failed"


@dataclass
class ImportResult:
    filename: str
    status: ImportStatus
    ride_id: int | None = None
    n_passes: int = 0
    flags_summary: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def import_bytes(
    session: Session,
    data: bytes,
    filename: str,
    *,
    replace: bool = False,
    thresholds: QualityThresholds | None = None,
) -> ImportResult:
    """Import one file in its own transaction. Never raises for bad input; see `status`."""
    existing = session.scalar(select(Ride).where(Ride.source_file_hash == sha256(data)))
    if existing is not None:
        return ImportResult(filename, ImportStatus.DUPLICATE, existing.id, existing.n_passes)

    try:
        parsed = parse(data, thresholds)
    except MbtCsvError as exc:
        return ImportResult(filename, ImportStatus.FAILED, error=str(exc))

    status = ImportStatus.IMPORTED
    twin = session.scalar(
        select(Ride).where(
            Ride.source == RideSource.MBT_CSV,
            Ride.started_at == parsed.started_at,
            Ride.ended_at == parsed.ended_at,
            Ride.n_passes == parsed.n_passes,
        )
    )
    if twin is not None:
        if not replace:
            return ImportResult(
                filename,
                ImportStatus.POSSIBLE_DUPLICATE,
                twin.id,
                twin.n_passes,
                error=POSSIBLE_DUPLICATE_HINT,
            )
        session.delete(twin)
        session.flush()
        status = ImportStatus.REPLACED

    ride = _to_ride(parsed, filename)
    session.add(ride)
    try:
        session.commit()
    except IntegrityError:
        # Another import of the same file won the race on the unique hash.
        session.rollback()
        winner = session.scalar(select(Ride).where(Ride.source_file_hash == parsed.file_sha256))
        if winner is None:
            raise
        return ImportResult(filename, ImportStatus.DUPLICATE, winner.id, winner.n_passes)
    return ImportResult(filename, status, ride.id, parsed.n_passes, flags_summary(parsed))


def import_path(
    session: Session,
    path: Path,
    *,
    replace: bool = False,
    thresholds: QualityThresholds | None = None,
) -> list[ImportResult]:
    """Import a file, or every `*.csv` directly inside a directory (not recursive)."""
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
    elif path.is_file():
        files = [path]
    else:
        return [ImportResult(str(path), ImportStatus.FAILED, error="no such file or directory")]
    return [
        import_bytes(session, f.read_bytes(), f.name, replace=replace, thresholds=thresholds)
        for f in files
    ]


def flags_summary(parsed: ParsedRide) -> dict[str, int]:
    return dict(sorted(Counter(f for p in parsed.passes for f in p.quality_flags).items()))


def _to_ride(parsed: ParsedRide, filename: str) -> Ride:
    return Ride(
        source=RideSource.MBT_CSV,
        source_format_version=parsed.format_version,
        source_file_hash=parsed.file_sha256,
        source_filename=filename,
        started_at=parsed.started_at,
        ended_at=parsed.ended_at,
        n_passes=parsed.n_passes,
        has_track=False,
        notes="; ".join(parsed.notes) or None,
        passes=[
            Pass(
                car_no=p.car_no,
                ts_utc=p.ts_utc,
                local_tz_abbr=p.local_tz_abbr,
                local_hour=p.local_hour,
                weekday=p.weekday,
                geom=None if p.lat is None else f"SRID=4326;POINT({p.lon!r} {p.lat!r})",
                avg_abs_mps=p.avg_abs_mps,
                max_abs_mps=p.max_abs_mps,
                pass_abs_mps=p.pass_abs_mps,
                approach_abs_mps=p.approach_abs_mps,
                max_rel_mps=p.max_rel_mps,
                approach_rel_mps=p.approach_rel_mps,
                pass_rel_mps=p.pass_rel_mps,
                slowdown_mps=p.slowdown_mps,
                approach_range_m=p.approach_range_m,
                closest_range_m=p.closest_range_m,
                pass_radar_count=p.pass_radar_count,
                approach_radar_count=p.approach_radar_count,
                track_seconds=p.track_seconds,
                rider_mps=p.rider_mps,
                quality_flags=list(p.quality_flags),
            )
            for p in parsed.passes
        ],
    )
