"""Shared pytest setup.

Tests marked ``db`` talk to Postgres (directly, or through the app lifespan,
which initialises the pose store). They are skipped when the compose database
isn't running: `docker compose up -d db`.
"""

import psycopg
import pytest

from app.config import DATABASE_URL


def _db_reachable() -> bool:
    try:
        psycopg.connect(DATABASE_URL, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


def pytest_collection_modifyitems(config, items):
    db_items = [item for item in items if item.get_closest_marker("db")]
    if db_items and not _db_reachable():
        skip = pytest.mark.skip(reason="Postgres not reachable; run `docker compose up -d db`")
        for item in db_items:
            item.add_marker(skip)
