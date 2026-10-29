"""ORM models (ARCHITECTURE.md data model). Units are explicit in column names; values are SI."""

from __future__ import annotations

import enum
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RideSource(enum.StrEnum):
    MBT_CSV = "mbt_csv"
    FIT = "fit"


class Ride(Base):
    __tablename__ = "rides"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[RideSource] = mapped_column(
        Enum(RideSource, name="ride_source", values_callable=lambda e: [m.value for m in e])
    )
    source_format_version: Mapped[str] = mapped_column(String(32))
    source_file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_filename: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_passes: Mapped[int] = mapped_column(Integer)
    has_track: Mapped[bool] = mapped_column(default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    passes: Mapped[list[Pass]] = relationship(
        back_populates="ride",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Pass.car_no",
    )

    __table_args__ = (Index("ix_rides_content", "source", "started_at", "ended_at", "n_passes"),)


class Pass(Base):
    __tablename__ = "passes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id", ondelete="CASCADE"), index=True)
    car_no: Mapped[int] = mapped_column(Integer)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_tz_abbr: Mapped[str] = mapped_column(String(8))
    local_hour: Mapped[int] = mapped_column(SmallInteger)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    geom: Mapped[object | None] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True), nullable=True
    )
    avg_abs_mps: Mapped[float] = mapped_column(Float)
    max_abs_mps: Mapped[float] = mapped_column(Float)
    pass_abs_mps: Mapped[float] = mapped_column(Float)
    approach_abs_mps: Mapped[float] = mapped_column(Float)
    max_rel_mps: Mapped[float] = mapped_column(Float)
    approach_rel_mps: Mapped[float] = mapped_column(Float)
    pass_rel_mps: Mapped[float] = mapped_column(Float)
    slowdown_mps: Mapped[float] = mapped_column(Float)
    approach_range_m: Mapped[float] = mapped_column(Float)
    closest_range_m: Mapped[float] = mapped_column(Float)
    pass_radar_count: Mapped[int] = mapped_column(Integer)
    approach_radar_count: Mapped[int] = mapped_column(Integer)
    track_seconds: Mapped[float] = mapped_column(Float)
    rider_mps: Mapped[float] = mapped_column(Float)
    way_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    match_distance_m: Mapped[float | None] = mapped_column(Float)
    quality_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")

    ride: Mapped[Ride] = relationship(back_populates="passes")

    __table_args__ = (
        UniqueConstraint("ride_id", "car_no", name="uq_passes_ride_car"),
        CheckConstraint("local_hour BETWEEN 0 AND 23", name="ck_passes_local_hour"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_passes_weekday"),
    )
