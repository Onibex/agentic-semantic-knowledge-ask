# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for the HANA connection pool.

Stubs the underlying hdbcli driver so the tests run without HANA or the
`hdbcli` package installed.
"""

from __future__ import annotations

import threading
import time

import pytest

from ask_sql_executor.infrastructure import hana_pool


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def execute(self, sql: str) -> None:
        if self._conn.fail_validate and sql.upper().startswith("SELECT 1 FROM DUMMY"):
            raise RuntimeError("connection dead")

    def fetchone(self) -> tuple:
        return (1,)

    def close(self) -> None:
        pass


class FakeConn:
    _counter = 0

    def __init__(self) -> None:
        FakeConn._counter += 1
        self.id = FakeConn._counter
        self.closed = False
        self.fail_validate = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_connect(monkeypatch):
    """Replace `_connect_hana` with a factory of `FakeConn` instances."""
    FakeConn._counter = 0
    created: list[FakeConn] = []

    def _factory(config):
        conn = FakeConn()
        created.append(conn)
        return conn

    monkeypatch.setattr(hana_pool, "_connect_hana", _factory)
    yield created
    hana_pool.reset_hana_pools()


_CFG = {"host": "h", "port": 443, "user": "u", "password": "p"}


def test_acquire_release_reuses_same_connection(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=2)
    a = pool.acquire()
    pool.release(a)
    b = pool.acquire()
    pool.release(b)
    assert a is b
    assert len(fake_connect) == 1


def test_release_failed_query_discards_connection(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=2)
    a = pool.acquire()
    pool.release(a, success=False)
    b = pool.acquire()
    assert b is not a
    assert a.closed is True
    assert len(fake_connect) == 2


def test_validate_rejects_stale_idle_connection(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=2)
    a = pool.acquire()
    a.fail_validate = True
    pool.release(a)
    # The pool must discard `a` and hand back a fresh conn.
    b = pool.acquire()
    assert b is not a
    assert a.closed is True


def test_overflow_caps_at_max(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=1, max_overflow=1, pool_timeout_s=0.2)
    a = pool.acquire()
    b = pool.acquire()  # uses overflow slot
    with pytest.raises(TimeoutError):
        pool.acquire()
    pool.release(a)
    pool.release(b)


def test_concurrent_acquire_release_under_threads(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=3)
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(20):
                conn = pool.acquire()
                time.sleep(0.001)
                pool.release(conn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    stats = pool.stats
    assert stats["issued"] == 0
    # Pool size cap holds: never opens more than pool_size + max_overflow.
    assert len(fake_connect) <= 3 + 10


def test_drain_closes_idle_connections(fake_connect):
    pool = hana_pool.HanaConnectionPool(_CFG, pool_size=3)
    conns = [pool.acquire() for _ in range(3)]
    for c in conns:
        pool.release(c)

    closed_count = pool.drain()
    assert closed_count == 3
    assert all(c.closed for c in conns)


def test_get_hana_pool_returns_singleton_per_key(fake_connect):
    p1 = hana_pool.get_hana_pool(_CFG)
    p2 = hana_pool.get_hana_pool(_CFG)
    p3 = hana_pool.get_hana_pool({**_CFG, "user": "other"})
    assert p1 is p2
    assert p3 is not p1


def test_reset_hana_pools_drains_all(fake_connect):
    p = hana_pool.get_hana_pool(_CFG)
    p.release(p.acquire())  # leaves one idle
    dropped = hana_pool.reset_hana_pools()
    assert dropped == 1
    # New get builds a fresh pool.
    assert hana_pool.get_hana_pool(_CFG) is not p
