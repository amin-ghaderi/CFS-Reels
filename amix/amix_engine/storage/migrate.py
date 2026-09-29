"""Apply Alembic revisions. This is the only production schema-creation path."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from amix.amix_engine.storage.errors import SchemaMismatch

AMIX_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = AMIX_ROOT / "alembic.ini"
HEAD = "0007_conversation_map"


def sqlite_url(database: Path) -> str:
    return "sqlite:///" + database.resolve().as_posix()


def upgrade_database(database: Path, revision: str = "head") -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(AMIX_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sqlite_url(database))
    try:
        command.upgrade(config, revision)
    except Exception as exc:
        raise SchemaMismatch(f"could not migrate {database}: {exc}") from exc


def current_revision(database: Path) -> str | None:
    engine = create_engine(sqlite_url(database))
    try:
        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def head_revision() -> str:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(AMIX_ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head() or HEAD
