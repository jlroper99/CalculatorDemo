from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bikeradar.ingest.mbt_csv import (
    FORMAT_VERSION,
    HEADER,
    ZERO_REL_SPEED_NOTE,
    HeaderDriftError,
    MbtCsvError,
    RowError,
    parse,
    sha256,
)
from tests.helpers import build_csv, fixture_bytes, fixture_rows


def test_fixture_has_four_passes() -> None:
    ride = parse(fixture_bytes())
    assert ride.format_version == FORMAT_VERSION
    assert [p.car_no for p in ride.passes] == [1, 2, 3, 4]
    assert ride.n_passes == 4


def test_same_second_passes_are_both_kept() -> None:
    passes = {p.car_no: p for p in parse(fixture_bytes()).passes}
    assert passes[2].ts_utc == passes[3].ts_utc == datetime.fromtimestamp(1793193397, UTC)
    assert passes[2].max_abs_mps != passes[3].max_abs_mps


def test_unit_mapping_for_car_1() -> None:
    p = parse(fixture_bytes()).passes[0]
    assert p.ts_utc == datetime(2026, 10, 28, 13, 15, 2, tzinfo=UTC)
    assert (p.local_hour, p.weekday, p.local_tz_abbr) == (7, 2, "MDT")
    assert (p.lat, p.lon) == (40.244512, -111.65821)
    assert p.max_abs_mps == 18.1
    assert p.pass_abs_mps == 15.1
    assert p.avg_abs_mps == 16.4
    assert p.approach_abs_mps == 18.1
    assert (p.max_rel_mps, p.approach_rel_mps, p.pass_rel_mps) == (12, 12, 9)
    assert p.slowdown_mps == 3
    assert (p.approach_range_m, p.closest_range_m) == (121, 3)
    assert (p.pass_radar_count, p.approach_radar_count) == (1, 1)
    assert p.track_seconds == 7
    assert p.rider_mps == 6.1


def test_ride_bounds_and_hash() -> None:
    data = fixture_bytes()
    ride = parse(data)
    assert ride.started_at == datetime(2026, 10, 28, 13, 15, 2, tzinfo=UTC)
    assert ride.ended_at == datetime(2026, 10, 28, 13, 19, 22, tzinfo=UTC)
    assert ride.file_sha256 == sha256(data)
    assert len(ride.file_sha256) == 64


def test_fixture_has_no_quality_flags_and_zero_closest_range_is_normal() -> None:
    ride = parse(fixture_bytes())
    assert all(p.quality_flags == () for p in ride.passes)
    assert ride.passes[2].closest_range_m == 0
    assert ride.notes == ()


def test_utf8_bom_is_accepted() -> None:
    assert parse(b"\xef\xbb\xbf" + fixture_bytes()).n_passes == 4


def test_crlf_line_endings_are_accepted() -> None:
    assert parse(fixture_bytes().replace(b"\n", b"\r\n")).n_passes == 4


@pytest.mark.parametrize(
    ("header", "message"),
    [
        (["car", *HEADER[1:]], "missing ['car #']"),
        (list(HEADER[:-1]), "missing ['avgriderspd']"),
        ([*HEADER, "extra"], "unexpected ['extra']"),
        ([HEADER[1], HEADER[0], *HEADER[2:]], "reordered"),
    ],
    ids=["renamed", "dropped", "added", "reordered"],
)
def test_header_drift_is_rejected(header: list[str], message: str) -> None:
    _, rows = fixture_rows()
    if len(header) != len(HEADER):
        rows = [r[: len(header)] + [""] * (len(header) - len(r)) for r in rows]
    with pytest.raises(HeaderDriftError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse(build_csv(header=header, rows=rows))


def test_empty_file_is_rejected() -> None:
    with pytest.raises(HeaderDriftError):
        parse(b"")


def test_header_only_is_rejected() -> None:
    with pytest.raises(RowError, match="no passes"):
        parse(build_csv(rows=[]))


def test_duplicate_car_number_is_rejected() -> None:
    with pytest.raises(RowError, match="duplicate 'car #' 2"):
        parse(build_csv(overrides={3: {"car #": "2"}}))


def test_non_numeric_value_names_line_and_column() -> None:
    with pytest.raises(RowError, match=r"line 3: column 'maxspdabs' value 'fast'"):
        parse(build_csv(overrides={2: {"maxspdabs": "fast"}}))


def test_non_integer_car_number_is_rejected() -> None:
    with pytest.raises(RowError, match="not an integer"):
        parse(build_csv(overrides={1: {"car #": "1.5"}}))


def test_bad_local_time_format_is_rejected() -> None:
    with pytest.raises(RowError, match="local time of day"):
        parse(build_csv(overrides={1: {"local time of day": "7:15:02 AM"}}))


def test_not_utf8_is_rejected() -> None:
    with pytest.raises(MbtCsvError, match="not UTF-8"):
        parse(b"\xff\xfe\x00")


@pytest.mark.parametrize(
    ("overrides", "flag"),
    [
        ({"maxspdrel": "0"}, "zero_rel_speed"),
        ({"approach_range": "0"}, "zero_range"),
        ({"maxspdabs": "46"}, "implausible_speed"),
        ({"avgspdabs": "-1"}, "implausible_speed"),
        ({"passspdrel": "8", "slowdown": "4"}, "rel_not_bucketed"),
        ({"slowdown": "6"}, "slowdown_mismatch"),
        ({"approach_spdabs": "25"}, "approach_identity_off"),
        ({"approach_range": "151"}, "range_exceeds_radar"),
        ({"lat": "0", "long": "0"}, "bad_coords"),
        ({"lat": "95"}, "bad_coords"),
        ({"local excel utc native": "46323.552106481"}, "tz_offset_mismatch"),
    ],
)
def test_quality_flags(overrides: dict[str, str], flag: str) -> None:
    passes = parse(build_csv(overrides={1: overrides})).passes
    assert passes[0].quality_flags == (flag,)
    assert all(p.quality_flags == () for p in passes[1:])


def test_blank_coordinates_are_flagged_and_dropped() -> None:
    p = parse(build_csv(overrides={1: {"lat": "", "long": ""}})).passes[0]
    assert p.quality_flags == ("bad_coords",)
    assert (p.lat, p.lon) == (None, None)


def test_out_of_range_coordinates_are_dropped() -> None:
    p = parse(build_csv(overrides={1: {"lat": "95"}})).passes[0]
    assert (p.lat, p.lon) == (None, None)


def test_all_zero_relative_speeds_add_a_ride_note() -> None:
    zero = {"maxspdrel": "0", "approachspdrel": "0", "passspdrel": "0", "slowdown": "0"}
    ride = parse(build_csv(overrides=dict.fromkeys((1, 2, 3, 4), zero)))
    assert ride.notes == (ZERO_REL_SPEED_NOTE,)
