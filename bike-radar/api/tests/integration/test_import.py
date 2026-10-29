from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bikeradar import cli
from bikeradar.config import get_settings
from bikeradar.db import get_engine
from bikeradar.ingest.service import ImportStatus, import_bytes, import_path
from bikeradar.models import Pass, Ride
from tests.helpers import FIXTURE, build_csv, fixture_bytes

pytestmark = pytest.mark.integration


def counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(Ride)) or 0,
        session.scalar(select(func.count()).select_from(Pass)) or 0,
    )


def test_import_fixture(session: Session) -> None:
    result = import_bytes(session, fixture_bytes(), "ride.csv")
    assert result.status == ImportStatus.IMPORTED
    assert result.n_passes == 4
    assert result.flags_summary == {}
    assert counts(session) == (1, 4)

    ride = session.get(Ride, result.ride_id)
    assert ride is not None
    assert ride.source.value == "mbt_csv"
    assert ride.source_format_version == "mbt_csv_v1"
    assert ride.source_filename == "ride.csv"
    assert not ride.has_track


def test_same_second_passes_are_stored(session: Session) -> None:
    import_bytes(session, fixture_bytes(), "ride.csv")
    rows = session.execute(
        text("SELECT car_no FROM passes WHERE ts_utc = to_timestamp(1793193397) ORDER BY car_no")
    ).scalars()
    assert list(rows) == [2, 3]


def test_geometry_is_stored_as_wgs84_point(session: Session) -> None:
    import_bytes(session, fixture_bytes(), "ride.csv")
    lon, lat, srid = session.execute(
        text("SELECT ST_X(geom), ST_Y(geom), ST_SRID(geom) FROM passes WHERE car_no = 1")
    ).one()
    assert (lon, lat, srid) == (-111.65821, 40.244512, 4326)


def test_reimport_is_a_noop(session: Session) -> None:
    first = import_bytes(session, fixture_bytes(), "ride.csv")
    again = import_bytes(session, fixture_bytes(), "renamed.csv")
    assert again.status == ImportStatus.DUPLICATE
    assert again.ride_id == first.ride_id
    assert counts(session) == (1, 4)


def test_reexport_with_same_content_needs_replace(session: Session) -> None:
    first = import_bytes(session, fixture_bytes(), "ride.csv")
    reexport = build_csv(overrides={1: {"avgspdabs": "16.5"}})

    skipped = import_bytes(session, reexport, "ride (1).csv")
    assert skipped.status == ImportStatus.POSSIBLE_DUPLICATE
    assert skipped.ride_id == first.ride_id
    assert counts(session) == (1, 4)

    replaced = import_bytes(session, reexport, "ride (1).csv", replace=True)
    assert replaced.status == ImportStatus.REPLACED
    assert replaced.ride_id != first.ride_id
    assert counts(session) == (1, 4)
    assert session.scalar(select(Pass.avg_abs_mps).where(Pass.car_no == 1)) == 16.5


def test_bad_file_writes_nothing(session: Session) -> None:
    bad = build_csv(overrides={4: {"maxspdabs": "n/a"}})
    result = import_bytes(session, bad, "bad.csv")
    assert result.status == ImportStatus.FAILED
    assert result.error is not None
    assert "line 5" in result.error
    assert counts(session) == (0, 0)


def test_quality_flags_are_stored(session: Session) -> None:
    result = import_bytes(session, build_csv(overrides={2: {"approach_range": "0"}}), "f.csv")
    assert result.flags_summary == {"zero_range": 1}
    flags = session.scalar(select(Pass.quality_flags).where(Pass.car_no == 2))
    assert flags == ["zero_range"]


def test_directory_import_reports_each_file(session: Session, tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(fixture_bytes())
    (tmp_path / "b.CSV").write_bytes(fixture_bytes())
    (tmp_path / "c.csv").write_bytes(b"not,a,ride\n1,2,3\n")
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.csv").write_bytes(fixture_bytes())

    results = import_path(session, tmp_path)
    assert [(r.filename, r.status) for r in results] == [
        ("a.csv", ImportStatus.IMPORTED),
        ("b.CSV", ImportStatus.DUPLICATE),
        ("c.csv", ImportStatus.FAILED),
    ]
    assert counts(session) == (1, 4)


def test_missing_path(session: Session, tmp_path: Path) -> None:
    [result] = import_path(session, tmp_path / "nope.csv")
    assert result.status == ImportStatus.FAILED


def test_upload_endpoint(client: TestClient) -> None:
    files = [
        ("files", ("ride.csv", fixture_bytes(), "text/csv")),
        ("files", ("again.csv", fixture_bytes(), "text/csv")),
        ("files", ("bad.csv", b'"car #"\n1\n', "text/csv")),
    ]
    response = client.post("/rides/upload", files=files)
    assert response.status_code == 200
    body = response.json()
    assert [r["status"] for r in body] == ["imported", "duplicate", "failed"]
    assert body[0]["n_passes"] == 4
    assert "header does not match" in body[2]["error"]

    rides = client.get("/rides").json()
    assert len(rides) == 1
    assert rides[0]["n_passes"] == 4
    assert client.get(f"/rides/{rides[0]['id']}").json()["source"] == "mbt_csv"
    assert client.get("/rides/999").status_code == 404


def test_passes_endpoint_masks_points_near_start_and_end(client: TestClient) -> None:
    ride_id = client.post(
        "/rides/upload", files=[("files", ("ride.csv", fixture_bytes(), "text/csv"))]
    ).json()[0]["ride_id"]
    body = client.get(f"/rides/{ride_id}/passes").json()
    assert body["type"] == "FeatureCollection"
    features = body["features"]
    assert [f["properties"]["car_no"] for f in features] == [1, 2, 3, 4]
    # Car 1 is the first pass and car 4 the last; cars 2 and 3 are ~370 m from car 1
    # and ~570 m from car 4, so only they keep their location.
    masked = [f["properties"]["location_masked"] for f in features]
    assert masked == [True, False, False, True]
    assert [f["geometry"] is None for f in features] == masked
    assert features[1]["geometry"] == {"type": "Point", "coordinates": [-111.65819, 40.24783]}
    assert features[0]["properties"]["max_abs_mps"] == 18.1
    assert client.get("/rides/999/passes").status_code == 404


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_cli_import(
    session: Session,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BIKERADAR_DATABASE_URL", database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        assert cli.main(["import", str(FIXTURE)]) == 0
        assert "imported" in capsys.readouterr().out
        assert cli.main(["import", str(FIXTURE), "--json"]) == 0
        assert '"status": "duplicate"' in capsys.readouterr().out
        assert cli.main(["import", str(FIXTURE.parent / "missing.csv")]) == 1
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
    assert counts(session) == (1, 4)
