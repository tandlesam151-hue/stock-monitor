"""PostgreSQL + TimescaleDB access layer for the stock monitor.

Owns a lazily-created connection pool and the schema bootstrap. Three logical
stores:

* ``alerts``  - a small keyed table for alert-cooldown bookkeeping (regular
  Postgres table; not time-series).
* ``ohlcv``   - a hypertable holding every 5-min OHLCV bar per symbol.
* ``signals`` - a hypertable holding the scored analysis snapshot per scan.

All write helpers are defensive: a database hiccup logs an error and returns a
falsy result rather than raising, so a DB problem never takes down a scan.
"""

import logging
import time
from contextlib import contextmanager
from typing import Optional

import atexit

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


# --- Circuit breaker --------------------------------------------------------
# A DB outage must never hang a scan. Each new connection is bounded by
# config.DB_CONNECT_TIMEOUT (libpq) and waiting for a pooled connection is
# bounded by config.DB_POOL_TIMEOUT. On top of that, this breaker remembers a
# failure so the *next* DB calls in the same scan short-circuit instantly
# instead of each waiting out the timeout again. After DB_BREAKER_COOLDOWN
# seconds the breaker resets and the next call is allowed to probe the DB.
class _DBUnavailable(Exception):
    """Raised internally when the breaker is open (DB known-bad)."""


_breaker_open_until = 0.0


def _breaker_open() -> bool:
    """True while the breaker is tripped (recent failure, still cooling down)."""
    return time.monotonic() < _breaker_open_until


def _trip_breaker(exc: Exception) -> None:
    """Open the breaker for DB_BREAKER_COOLDOWN seconds after a failure."""
    global _breaker_open_until
    cooldown = config.DB_BREAKER_COOLDOWN
    _breaker_open_until = time.monotonic() + cooldown
    logger.error(
        f"Database unavailable ({exc}); circuit breaker open for {cooldown}s, "
        f"DB calls will short-circuit until then"
    )


def _reset_breaker() -> None:
    """Close the breaker after a successful DB call."""
    global _breaker_open_until
    _breaker_open_until = 0.0


def _conninfo() -> str:
    """Build a libpq connection string from individual config settings.

    ``connect_timeout`` bounds how long libpq waits to establish each new TCP
    connection, so a dead/unreachable DB fails fast instead of hanging the scan.
    """
    return psycopg.conninfo.make_conninfo(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        connect_timeout=config.DB_CONNECT_TIMEOUT,
    )


def get_pool() -> ConnectionPool:
    """Return the process-wide connection pool, creating it on first use.

    Connections are autocommit: every statement we run is a self-contained
    upsert/select, so explicit transactions add no value here.

    ``open=False`` + an explicit ``open()`` with a bounded ``wait`` would still
    block on a dead DB, so the pool is created lazily and unopened; the first
    ``connection()`` acquisition is what bounds the wait via DB_POOL_TIMEOUT.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            min_size=1,
            max_size=5,
            timeout=config.DB_POOL_TIMEOUT,
            open=True,
            kwargs={"autocommit": True},
        )
        # Ensure pooled worker threads are shut down cleanly on interpreter exit
        # (otherwise short-lived scripts emit "couldn't stop thread" warnings).
        atexit.register(close_pool)
    return _pool


@contextmanager
def connection():
    """Yield a pooled connection, bounded by DB_POOL_TIMEOUT.

    Raises psycopg_pool.PoolTimeout if no connection becomes available within
    the pool timeout, rather than blocking indefinitely.
    """
    with get_pool().connection(timeout=config.DB_POOL_TIMEOUT) as conn:
        yield conn


def close_pool() -> None:
    """Close the pool (used on shutdown / in tests)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# --- Schema -----------------------------------------------------------------

_SCHEMA = [
    # Alert cooldown bookkeeping. last_sent is a real timestamp now (the SQLite
    # version stored epoch seconds as a float).
    """
    CREATE TABLE IF NOT EXISTS alerts (
        symbol     TEXT        NOT NULL,
        alert_type TEXT        NOT NULL,
        last_sent  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (symbol, alert_type)
    )
    """,
    # 5-min OHLCV bars. Hypertable partitioned on ts.
    """
    CREATE TABLE IF NOT EXISTS ohlcv (
        symbol TEXT             NOT NULL,
        ts     TIMESTAMPTZ      NOT NULL,
        open   DOUBLE PRECISION,
        high   DOUBLE PRECISION,
        low    DOUBLE PRECISION,
        close  DOUBLE PRECISION,
        volume BIGINT,
        PRIMARY KEY (symbol, ts)
    )
    """,
    "SELECT create_hypertable('ohlcv', 'ts', if_not_exists => TRUE)",
    # Scored analysis snapshot per scan. Hypertable partitioned on ts.
    """
    CREATE TABLE IF NOT EXISTS signals (
        symbol     TEXT             NOT NULL,
        ts         TIMESTAMPTZ      NOT NULL,
        price      DOUBLE PRECISION,
        change_pct DOUBLE PRECISION,
        direction  TEXT,
        score      INTEGER,
        bull_score INTEGER,
        bear_score INTEGER,
        confidence INTEGER,
        level      TEXT,
        signals    JSONB,
        PRIMARY KEY (symbol, ts)
    )
    """,
    "SELECT create_hypertable('signals', 'ts', if_not_exists => TRUE)",
]


def init_schema() -> None:
    """Create the alerts table and the ohlcv/signals hypertables if missing."""
    with connection() as conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)
    logger.info("Database schema initialized (alerts + ohlcv/signals hypertables)")


# --- Alert cooldown helpers -------------------------------------------------

def can_alert(symbol: str, alert_type: str, cooldown_mins: int) -> bool:
    """Return True if enough time has passed since the last alert of this type.

    Fail-open: if the DB is unavailable (breaker open or query fails) we return
    True so a DB outage never *silences* alerting. The trade-off is that during
    an outage the cooldown can't be enforced, so alerts may repeat each scan.
    """
    if _breaker_open():
        logger.debug(f"can_alert short-circuited (breaker open) for {symbol}")
        return True
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT EXTRACT(EPOCH FROM (now() - last_sent)) / 60.0 "
                "FROM alerts WHERE symbol = %s AND alert_type = %s",
                (symbol, alert_type),
            ).fetchone()
        _reset_breaker()
        if not row:
            return True
        return float(row[0]) > cooldown_mins
    except Exception as e:
        _trip_breaker(e)
        return True


def record_alert(symbol: str, alert_type: str) -> bool:
    """Record that an alert was just sent (upsert last_sent = now())."""
    if _breaker_open():
        logger.debug(f"record_alert short-circuited (breaker open) for {symbol}")
        return False
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO alerts (symbol, alert_type, last_sent) "
                "VALUES (%s, %s, now()) "
                "ON CONFLICT (symbol, alert_type) "
                "DO UPDATE SET last_sent = now()",
                (symbol, alert_type),
            )
        _reset_breaker()
        return True
    except Exception as e:
        _trip_breaker(e)
        return False


# --- Time-series persistence ------------------------------------------------

def insert_ohlcv(symbol: str, df: pd.DataFrame) -> int:
    """Upsert the OHLCV bars in `df` (indexed by timestamp) for `symbol`.

    Returns the number of rows written, or 0 on error / empty input.
    """
    if df is None or df.empty:
        return 0
    if _breaker_open():
        logger.debug(f"insert_ohlcv short-circuited (breaker open) for {symbol}")
        return 0
    try:
        rows = []
        for idx, r in df.iterrows():
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            rows.append((
                symbol, ts,
                float(r["Open"]), float(r["High"]), float(r["Low"]),
                float(r["Close"]), int(r["Volume"]),
            ))
        with connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ohlcv (symbol, ts, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (symbol, ts) DO UPDATE SET "
                "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, "
                "close = EXCLUDED.close, volume = EXCLUDED.volume",
                rows,
            )
        _reset_breaker()
        return len(rows)
    except Exception as e:
        _trip_breaker(e)
        return 0


def insert_signal(symbol: str, ts, res: dict) -> bool:
    """Upsert one scored analysis snapshot for `symbol` at bar time `ts`."""
    if _breaker_open():
        logger.debug(f"insert_signal short-circuited (breaker open) for {symbol}")
        return False
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO signals "
                "(symbol, ts, price, change_pct, direction, score, "
                " bull_score, bear_score, confidence, level, signals) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (symbol, ts) DO UPDATE SET "
                "price = EXCLUDED.price, change_pct = EXCLUDED.change_pct, "
                "direction = EXCLUDED.direction, score = EXCLUDED.score, "
                "bull_score = EXCLUDED.bull_score, bear_score = EXCLUDED.bear_score, "
                "confidence = EXCLUDED.confidence, level = EXCLUDED.level, "
                "signals = EXCLUDED.signals",
                (
                    symbol, ts, res.get("price"), res.get("change_pct"),
                    res.get("direction"), res.get("score"), res.get("bull_score"),
                    res.get("bear_score"), res.get("confidence"), res.get("level"),
                    Jsonb(res.get("signals")),
                ),
            )
        _reset_breaker()
        return True
    except Exception as e:
        _trip_breaker(e)
        return False
