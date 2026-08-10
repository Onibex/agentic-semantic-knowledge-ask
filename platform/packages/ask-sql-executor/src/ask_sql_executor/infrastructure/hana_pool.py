"""Thread-safe HANA connection pool for the SQL executor hot path.

Before this module the orchestrator opened a fresh hdbcli connection per
`/v1/query` SQL_EXECUTION request (TCP + TLS handshake + auth, ~100–300 ms
each). With FastAPI now dispatching requests to a thread pool, 40 concurrent
requests would mean 40 fresh handshakes — HANA Cloud's `M_CONNECTIONS` view
caps connection counts per tenant and the handshake latency dominates the
end-to-end query time.

Pool semantics (kept deliberately small):
- `pool_size` connections kept warm; up to `max_overflow` extra under load.
- `acquire()` validates the connection with `SELECT 1 FROM DUMMY` before
  handing it out — stale/dead conns are dropped silently.
- `release(success=True)` returns the conn to the idle queue; with
  `success=False` the conn is closed (it may be in an inconsistent state).
- `pool_recycle_s` forces re-handshake periodically so HANA's idle-session
  reaper doesn't surprise us.
- One pool per `(host, port, user)` tuple — kept in `_pool_cache`.
- `reset_hana_pools()` drains every pool; wired into the orchestrator's
  `reset_singletons()` so an admin-UI config change can rebuild pools with
  fresh credentials on the next request.

Each gunicorn worker has its own pools (the cache is module-level, not
shared cross-process). With `pool_size=5` and `WEB_CONCURRENCY=2`, each
pod warms up to 10 HANA conns — well within tenant limits.
"""

from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_POOL_SIZE = 5
_DEFAULT_MAX_OVERFLOW = 10
_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_RECYCLE_S = 1800.0


def _connect_hana(config: dict[str, Any]) -> Any:
    """Open a fresh hdbcli connection. Isolated so tests can monkeypatch it."""
    from hdbcli import dbapi  # type: ignore[import-not-found]

    kwargs: dict[str, Any] = dict(
        address=config["host"],
        port=int(config["port"]),
        user=config["user"],
        password=config["password"],
        encrypt=True,
        sslValidateCertificate=False,
    )
    if config.get("schema"):
        kwargs["currentSchema"] = config["schema"]
    return dbapi.connect(**kwargs)


class HanaConnectionPool:
    def __init__(
        self,
        config: dict[str, Any],
        pool_size: int = _DEFAULT_POOL_SIZE,
        max_overflow: int = _DEFAULT_MAX_OVERFLOW,
        pool_timeout_s: float = _DEFAULT_TIMEOUT_S,
        pool_recycle_s: float = _DEFAULT_RECYCLE_S,
    ) -> None:
        self._config = config
        self._pool_size = pool_size
        self._max = pool_size + max_overflow
        self._timeout_s = pool_timeout_s
        self._recycle_s = pool_recycle_s
        self._idle: Queue = Queue()
        self._lock = threading.Lock()
        self._issued = 0

    def _is_stale(self, created_at: float) -> bool:
        return (time.monotonic() - created_at) > self._recycle_s

    @staticmethod
    def _validate(conn: Any) -> bool:
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT 1 FROM DUMMY")
                cur.fetchone()
            finally:
                cur.close()
            return True
        except Exception:  # noqa: BLE001 — dead conn
            return False

    @staticmethod
    def _close_quietly(conn: Any) -> None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def acquire(self) -> Any:
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                conn, created_at = self._idle.get_nowait()
            except Empty:
                conn = None
                created_at = 0.0

            if conn is not None:
                if self._is_stale(created_at) or not self._validate(conn):
                    self._close_quietly(conn)
                    continue
                with self._lock:
                    self._issued += 1
                return conn

            # No idle conn: try to open a new one if under cap.
            with self._lock:
                if self._issued < self._max:
                    self._issued += 1
                    must_create = True
                else:
                    must_create = False

            if must_create:
                try:
                    return _connect_hana(self._config)
                except Exception:
                    with self._lock:
                        self._issued -= 1
                    raise

            if time.monotonic() > deadline:
                raise TimeoutError(f"HANA pool exhausted (issued={self._issued}, max={self._max})")
            time.sleep(0.05)

    def release(self, conn: Any, *, success: bool = True) -> None:
        with self._lock:
            self._issued -= 1
        if not success:
            self._close_quietly(conn)
            return
        try:
            self._idle.put_nowait((conn, time.monotonic()))
        except Exception:  # noqa: BLE001 — queue full, drop conn
            self._close_quietly(conn)

    def drain(self) -> int:
        """Close every idle connection. Returns count drained.

        In-flight connections are NOT touched — they will be closed when
        the caller releases them with `success=False` after the rebuild.
        """
        n = 0
        while True:
            try:
                conn, _ = self._idle.get_nowait()
            except Empty:
                return n
            self._close_quietly(conn)
            n += 1

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "idle": self._idle.qsize(),
                "issued": self._issued,
                "max": self._max,
            }


# ── Process-wide registry ────────────────────────────────────────────────────

_registry_lock = threading.Lock()
_pool_cache: dict[str, HanaConnectionPool] = {}


def _pool_key(config: dict[str, Any]) -> str:
    return f"{config.get('host')}:{config.get('port')}:{config.get('user')}"


def get_hana_pool(config: dict[str, Any]) -> HanaConnectionPool:
    """Return the pool for the given HANA config, creating it on first use."""
    key = _pool_key(config)
    pool = _pool_cache.get(key)
    if pool is not None:
        return pool
    with _registry_lock:
        pool = _pool_cache.get(key)
        if pool is None:
            pool_cfg = config.get("pool", {}) or {}
            pool = HanaConnectionPool(
                config,
                pool_size=int(pool_cfg.get("size", _DEFAULT_POOL_SIZE)),
                max_overflow=int(pool_cfg.get("max_overflow", _DEFAULT_MAX_OVERFLOW)),
                pool_timeout_s=float(pool_cfg.get("timeout_s", _DEFAULT_TIMEOUT_S)),
                pool_recycle_s=float(pool_cfg.get("recycle_s", _DEFAULT_RECYCLE_S)),
            )
            _pool_cache[key] = pool
        return pool


def reset_hana_pools() -> int:
    """Drain and drop every cached pool. Returns the number of pools dropped."""
    with _registry_lock:
        count = len(_pool_cache)
        for pool in _pool_cache.values():
            pool.drain()
        _pool_cache.clear()
        return count
