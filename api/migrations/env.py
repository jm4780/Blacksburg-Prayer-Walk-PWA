"""Alembic environment.

The database URL comes from BPW_DATABASE_URL via the application settings, never from
alembic.ini — a URL in the ini file would be a committed credential.

`render_as_batch` is on because SQLite cannot ALTER a column in place; batch mode
rebuilds the table instead. That keeps the same migration scripts working against both
the SQLite used for local work and the PostgreSQL a real deployment uses.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from api.app.config import settings
from api.app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings().database_url, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
