from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from bikeradar.ingest.mbt_csv import QualityThresholds


class Settings(BaseSettings):
    """Settings from environment variables prefixed `BIKERADAR_` (see `.env.example`)."""

    model_config = SettingsConfigDict(
        env_prefix="BIKERADAR_", env_file=(".env", "../.env"), extra="ignore"
    )

    database_url: str = "postgresql+psycopg://bikeradar:bikeradar@localhost:5432/bikeradar"
    max_upload_bytes: int = 20 * 1024 * 1024
    privacy_endpoint_radius_m: float = 300.0
    cors_origins: list[str] = ["http://localhost:3000"]

    implausible_speed_mps: float = 45.0
    max_radar_range_m: float = 150.0
    approach_identity_tolerance_mps: float = 3.0
    tz_offset_tolerance_h: float = 0.25

    def quality_thresholds(self) -> QualityThresholds:
        return QualityThresholds(
            implausible_speed_mps=self.implausible_speed_mps,
            max_radar_range_m=self.max_radar_range_m,
            approach_identity_tolerance_mps=self.approach_identity_tolerance_mps,
            tz_offset_tolerance_h=self.tz_offset_tolerance_h,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
