"""Parser for the MyBikeTraffic per-ride CSV export (`mbt_csv_v1`, features/001).

Pure: bytes in, `ParsedRide` out, no database access. One row is one car pass already
detected by MBT, so there is no pass detection here (ADR-003).
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

FORMAT_VERSION = "mbt_csv_v1"

HEADER: tuple[str, ...] = (
    "car #",
    "utc timestamp",
    "utc excel native",
    "local excel utc native",
    "local time of day",
    "lat",
    "long",
    "avgspdabs",
    "maxspdabs",
    "pass_spdabs",
    "maxspdrel",
    "approachspdrel",
    "passspdrel",
    "slowdown",
    "pass_radarcnt",
    "approach_spdabs",
    "approach_range",
    "closest_range",
    "approach_radarcnt",
    "passlength",
    "avgriderspd",
)

# CSV column -> (PassRecord field, scale to SI). Every scale is 1.0 because the export is
# already SI (verified on real exports, features/001). TODO(verify) units with the MBT
# maintainer; if they differ for some accounts, only this table and FORMAT_VERSION change.
FLOAT_COLUMNS: dict[str, tuple[str, float]] = {
    "avgspdabs": ("avg_abs_mps", 1.0),
    "maxspdabs": ("max_abs_mps", 1.0),
    "pass_spdabs": ("pass_abs_mps", 1.0),
    "maxspdrel": ("max_rel_mps", 1.0),
    "approachspdrel": ("approach_rel_mps", 1.0),
    "passspdrel": ("pass_rel_mps", 1.0),
    "slowdown": ("slowdown_mps", 1.0),
    "approach_spdabs": ("approach_abs_mps", 1.0),
    "approach_range": ("approach_range_m", 1.0),
    "closest_range": ("closest_range_m", 1.0),
    "passlength": ("track_seconds", 1.0),
    "avgriderspd": ("rider_mps", 1.0),
}
INT_COLUMNS: dict[str, str] = {
    "car #": "car_no",
    "utc timestamp": "ts_epoch_s",
    "pass_radarcnt": "pass_radar_count",
    "approach_radarcnt": "approach_radar_count",
}
EXCEL_COLUMNS = ("utc excel native", "local excel utc native")

LOCAL_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ([A-Z]{2,5})$")
VARIA_BUCKET_MPS = 3.0

ZERO_REL_SPEED_NOTE = (
    "every pass has zero relative speed; the radar may not report speeds "
    "(e.g. Rearvue 820 on older devices)"
)


class MbtCsvError(ValueError):
    """The file is not a valid `mbt_csv_v1` export. Nothing from it may be imported."""


class HeaderDriftError(MbtCsvError):
    pass


class RowError(MbtCsvError):
    pass


@dataclass(frozen=True)
class QualityThresholds:
    implausible_speed_mps: float = 45.0  # about 100 mph
    max_radar_range_m: float = 150.0  # Varia tops out near 140 m
    approach_identity_tolerance_mps: float = VARIA_BUCKET_MPS
    tz_offset_tolerance_h: float = 0.25


@dataclass(frozen=True)
class PassRecord:
    car_no: int
    ts_utc: datetime
    local_tz_abbr: str
    local_hour: int
    weekday: int  # 0 = Monday
    lat: float | None
    lon: float | None
    avg_abs_mps: float
    max_abs_mps: float
    pass_abs_mps: float
    approach_abs_mps: float
    max_rel_mps: float
    approach_rel_mps: float
    pass_rel_mps: float
    slowdown_mps: float
    approach_range_m: float
    closest_range_m: float
    pass_radar_count: int
    approach_radar_count: int
    track_seconds: float
    rider_mps: float
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedRide:
    format_version: str
    file_sha256: str
    started_at: datetime
    ended_at: datetime
    passes: tuple[PassRecord, ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def n_passes(self) -> int:
        return len(self.passes)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(data: bytes, thresholds: QualityThresholds | None = None) -> ParsedRide:
    """Parse one MBT per-ride CSV. Raises `MbtCsvError` (never partially succeeds)."""
    thresholds = thresholds or QualityThresholds()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MbtCsvError(f"file is not UTF-8 text: {exc}") from exc

    first_line = text.splitlines()[0] if text else ""
    header = next(csv.reader([first_line]), [])
    validate_header(header)

    frame = pd.read_csv(
        io.StringIO(text),
        dtype=str,
        keep_default_na=False,
        skipinitialspace=False,
    )
    if frame.empty:
        raise RowError("file has a header but no passes")

    passes = tuple(
        _parse_row({str(k): str(v) for k, v in row.items()}, line_no=i + 2, thresholds=thresholds)
        for i, row in enumerate(frame.to_dict(orient="records"))
    )
    seen: dict[int, int] = {}
    for i, p in enumerate(passes):
        if p.car_no in seen:
            raise RowError(
                f"line {i + 2}: duplicate 'car #' {p.car_no} (first on line {seen[p.car_no] + 2})"
            )
        seen[p.car_no] = i

    notes: list[str] = []
    if all("zero_rel_speed" in p.quality_flags for p in passes):
        notes.append(ZERO_REL_SPEED_NOTE)

    return ParsedRide(
        format_version=FORMAT_VERSION,
        file_sha256=sha256(data),
        started_at=min(p.ts_utc for p in passes),
        ended_at=max(p.ts_utc for p in passes),
        passes=passes,
        notes=tuple(notes),
    )


def validate_header(header: Sequence[str]) -> None:
    actual = [h.strip() for h in header]
    if actual == list(HEADER):
        return
    expected = list(HEADER)
    missing = [c for c in expected if c not in actual]
    unexpected = [c for c in actual if c not in expected]
    parts = []
    if missing:
        parts.append(f"missing {missing}")
    if unexpected:
        parts.append(f"unexpected {unexpected}")
    if not parts:
        parts.append(f"columns reordered; got {actual}")
    raise HeaderDriftError(
        f"header does not match {FORMAT_VERSION}: "
        + "; ".join(parts)
        + ". The MBT export format may have changed; update the parser deliberately."
    )


def _parse_row(row: dict[str, str], *, line_no: int, thresholds: QualityThresholds) -> PassRecord:
    ints = {name: _int(row, col, line_no) for col, name in INT_COLUMNS.items()}
    floats = {
        name: _float(row, col, line_no) * scale for col, (name, scale) in FLOAT_COLUMNS.items()
    }
    excel = {col: _float(row, col, line_no) for col in EXCEL_COLUMNS}
    lat = _optional_float(row, "lat", line_no)
    lon = _optional_float(row, "long", line_no)

    ts_utc = datetime.fromtimestamp(ints["ts_epoch_s"], tz=UTC)
    local_raw = row["local time of day"].strip()
    match = LOCAL_TIME_RE.match(local_raw)
    if not match:
        raise RowError(
            f"line {line_no}: 'local time of day' {local_raw!r} is not 'YYYY-MM-DD HH:MM:SS TZ'"
        )
    local_wall = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    tz_abbr = match.group(2)

    flags = _quality_flags(
        floats,
        lat=lat,
        lon=lon,
        wall_offset_h=(local_wall - ts_utc.replace(tzinfo=None)).total_seconds() / 3600,
        excel_offset_h=(excel["local excel utc native"] - excel["utc excel native"]) * 24,
        thresholds=thresholds,
    )
    if lat is None or lon is None or "bad_coords" in flags:
        lat = lon = None

    return PassRecord(
        car_no=ints["car_no"],
        ts_utc=ts_utc,
        local_tz_abbr=tz_abbr,
        local_hour=local_wall.hour,
        weekday=local_wall.weekday(),
        lat=lat,
        lon=lon,
        pass_radar_count=ints["pass_radar_count"],
        approach_radar_count=ints["approach_radar_count"],
        quality_flags=flags,
        **floats,
    )


def _quality_flags(
    v: dict[str, float],
    *,
    lat: float | None,
    lon: float | None,
    wall_offset_h: float,
    excel_offset_h: float,
    thresholds: QualityThresholds,
) -> tuple[str, ...]:
    flags: list[str] = []
    rel = (v["max_rel_mps"], v["approach_rel_mps"], v["pass_rel_mps"])
    absolute = (v["avg_abs_mps"], v["max_abs_mps"], v["pass_abs_mps"], v["approach_abs_mps"])
    if v["max_rel_mps"] == 0 or v["approach_rel_mps"] == 0:
        flags.append("zero_rel_speed")
    if v["approach_range_m"] == 0:
        flags.append("zero_range")
    if v["max_abs_mps"] > thresholds.implausible_speed_mps or any(s < 0 for s in absolute):
        flags.append("implausible_speed")
    if any(not math.isclose(s % VARIA_BUCKET_MPS, 0.0, abs_tol=1e-6) for s in rel):
        flags.append("rel_not_bucketed")
    if abs(v["slowdown_mps"] - (v["approach_rel_mps"] - v["pass_rel_mps"])) > 0.01:
        flags.append("slowdown_mismatch")
    identity = v["approach_abs_mps"] - v["rider_mps"] - v["approach_rel_mps"]
    if abs(identity) > thresholds.approach_identity_tolerance_mps:
        flags.append("approach_identity_off")
    if max(v["approach_range_m"], v["closest_range_m"]) > thresholds.max_radar_range_m:
        flags.append("range_exceeds_radar")
    if (
        lat is None
        or lon is None
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        or (lat == 0 and lon == 0)
    ):
        flags.append("bad_coords")
    if abs(wall_offset_h - excel_offset_h) > thresholds.tz_offset_tolerance_h:
        flags.append("tz_offset_mismatch")
    return tuple(flags)


def _cell(row: dict[str, str], col: str) -> str:
    return row[col].strip()


def _float(row: dict[str, str], col: str, line_no: int) -> float:
    raw = _cell(row, col)
    try:
        value = float(raw)
    except ValueError:
        raise RowError(f"line {line_no}: column {col!r} value {raw!r} is not a number") from None
    if not math.isfinite(value):
        raise RowError(f"line {line_no}: column {col!r} value {raw!r} is not finite")
    return value


def _optional_float(row: dict[str, str], col: str, line_no: int) -> float | None:
    return None if _cell(row, col) == "" else _float(row, col, line_no)


def _int(row: dict[str, str], col: str, line_no: int) -> int:
    value = _float(row, col, line_no)
    if not value.is_integer():
        raise RowError(f"line {line_no}: column {col!r} value {value!r} is not an integer")
    return int(value)
