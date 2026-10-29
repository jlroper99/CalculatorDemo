from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context
from bikeradar.config import get_settings
from bikeradar.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Tests pass their own URL via config attributes; everything else uses settings.
url = config.attributes.get("database_url") or get_settings().database_url


def include_object(obj: object, name: str | None, type_: str, *args: object) -> bool:
    # PostGIS owns spatial_ref_sys; never autogenerate a drop for it.
    return not (type_ == "table" and name == "spatial_ref_sys")


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()
