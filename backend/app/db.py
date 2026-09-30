"""Thin data-access layer over Supabase's Postgres database.

We use raw parameterized SQL through psycopg rather than an ORM: the schema is
small and stable, the queries are simple CRUD + a few joins, and an ORM would
mostly add indirection without buying much here. LangGraph's own Postgres
checkpointer manages its tables separately (see graph.py) and uses psycopg
under the hood too, so this keeps the whole backend on one DB driver.
"""

from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb  # re-exported: wrap dict params so psycopg sends them as jsonb
from psycopg_pool import ConnectionPool

from app.config import get_settings

__all__ = ["init_pool", "close_pool", "get_cursor", "fetch_one", "fetch_all", "execute", "Jsonb"]

_pool: ConnectionPool | None = None


def init_pool() -> None:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            open=True,
            # Supabase's pooler silently drops idle connections; without this check,
            # the pool can hand out a connection that's already dead server-side,
            # surfacing as "server closed the connection unexpectedly" mid-query.
            check=ConnectionPool.check_connection,
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_cursor():
    if _pool is None:
        init_pool()
    assert _pool is not None
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur


def fetch_one(query: str, params: tuple | dict = ()) -> dict | None:
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def fetch_all(query: str, params: tuple | dict = ()) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def execute(query: str, params: tuple | dict = ()) -> None:
    with get_cursor() as cur:
        cur.execute(query, params)
