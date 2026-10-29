"""rides and passes (features/001)

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    ride_source = postgresql.ENUM("mbt_csv", "fit", name="ride_source")
    op.create_table(
        "rides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", ride_source, nullable=False),
        sa.Column("source_format_version", sa.String(32), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source_filename", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_passes", sa.Integer(), nullable=False),
        sa.Column("has_track", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_rides_content", "rides", ["source", "started_at", "ended_at", "n_passes"])
    op.create_table(
        "passes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("car_no", sa.Integer(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_tz_abbr", sa.String(8), nullable=False),
        sa.Column("local_hour", sa.SmallInteger(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        *[
            sa.Column(name, sa.Float(), nullable=False)
            for name in (
                "avg_abs_mps",
                "max_abs_mps",
                "pass_abs_mps",
                "approach_abs_mps",
                "max_rel_mps",
                "approach_rel_mps",
                "pass_rel_mps",
                "slowdown_mps",
                "approach_range_m",
                "closest_range_m",
            )
        ],
        sa.Column("pass_radar_count", sa.Integer(), nullable=False),
        sa.Column("approach_radar_count", sa.Integer(), nullable=False),
        sa.Column("track_seconds", sa.Float(), nullable=False),
        sa.Column("rider_mps", sa.Float(), nullable=False),
        sa.Column("way_id", sa.BigInteger()),
        sa.Column("match_distance_m", sa.Float()),
        sa.Column(
            "quality_flags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.UniqueConstraint("ride_id", "car_no", name="uq_passes_ride_car"),
        sa.CheckConstraint("local_hour BETWEEN 0 AND 23", name="ck_passes_local_hour"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_passes_weekday"),
    )
    op.create_index("ix_passes_ride_id", "passes", ["ride_id"])
    op.create_index("ix_passes_way_id", "passes", ["way_id"])
    op.create_index("idx_passes_geom", "passes", ["geom"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_table("passes")
    op.drop_table("rides")
    op.execute("DROP TYPE IF EXISTS ride_source")
