"""SQLite connection setup for a project database.

Journal mode is DELETE, not WAL. WAL adds ``-wal`` and ``-shm`` sidecars that
file-sync clients corrupt, and this app has one writer. Synced multi-machine
editing of one project is not supported.

``synchronous=FULL`` keeps a commit durable after a crash for that single writer.
``busy_timeout`` waits briefly if the file is momentarily busy.
``foreign_keys`` is off by default in SQLite and is enabled on every connection.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from amix.amix_engine.storage.migrate import sqlite_url


def create_project_engine(database: Path, *, read_only: bool) -> Engine:
    # Job orchestration runs on worker threads in this process. SQLite still
    # has one writer; connections may be checked out on those threads.
    engine = create_engine(
        sqlite_url(database),
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if read_only:
            cursor.execute("PRAGMA query_only=ON")
        else:
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    return engine
