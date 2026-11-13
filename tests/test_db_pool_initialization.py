"""#327–#331: concurrent first use must share one database pool."""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock

import pytest
import psycopg

import logger


def test_concurrent_first_use_creates_one_pool(monkeypatch):
    start = threading.Barrier(8)
    constructors = threading.Barrier(2)

    def make_pool(*_args, **_kwargs):
        # An unlocked initializer lets a second constructor in. With a lock,
        # the first constructor times out here and all callers share its pool.
        try:
            constructors.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return object()

    factory = Mock(side_effect=make_pool)
    monkeypatch.setattr(logger, "_pool", None)
    monkeypatch.setattr(logger, "ConnectionPool", factory)

    def first_use(_index):
        start.wait(timeout=5)
        return logger.get_db_pool()

    with ThreadPoolExecutor(max_workers=8) as executor:
        pools = list(executor.map(first_use, range(8)))
    assert factory.call_count == 1
    assert all(pool is pools[0] for pool in pools)
    assert logger.get_db_pool() is pools[0]


def test_failed_constructor_can_be_retried(monkeypatch):
    pool = object()
    factory = Mock(side_effect=[RuntimeError("setup failed"), pool])
    monkeypatch.setattr(logger, "_pool", None)
    monkeypatch.setattr(logger, "ConnectionPool", factory)
    with pytest.raises(RuntimeError, match="setup failed"):
        logger.get_db_pool()
    assert logger._pool is None
    assert logger.get_db_pool() is pool
    assert factory.call_count == 2


def test_query_failure_returns_connection_to_shared_pool(db, monkeypatch):
    monkeypatch.setattr(logger, "_pool", None)
    monkeypatch.setattr(logger, "DB_HOST", f"{db.info.host} port={db.info.port}")
    monkeypatch.setattr(logger, "DB_USER", db.info.user)
    monkeypatch.setattr(logger, "DB_NAME", db.info.dbname)
    pool = logger.get_db_pool()
    try:
        with pytest.raises(psycopg.errors.DivisionByZero):
            with logger.get_db() as conn:
                conn.execute("SELECT 1 / 0")
        with logger.get_db() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
        assert logger.get_db_pool() is pool
    finally:
        pool.close()
