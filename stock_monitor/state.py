"""Alert-cooldown state, backed by PostgreSQL + TimescaleDB.

This module preserves the original public API (``init_db``, ``can_alert``,
``record_alert``) so callers (alert_engine, main) need no changes. The actual
storage now lives in Postgres via :mod:`db`; the cooldown semantics are
unchanged: an alert of a given (symbol, alert_type) may only fire once per
``cooldown_mins`` window.
"""

import logging

import db

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Initialize the database schema (alerts table + hypertables)."""
    try:
        db.init_schema()
    except Exception as e:
        logger.error(f"Database init error: {e}")


def can_alert(symbol: str, alert_type: str, cooldown_mins: int) -> bool:
    """Return True if the cooldown window has elapsed for this symbol/type."""
    return db.can_alert(symbol, alert_type, cooldown_mins)


def record_alert(symbol: str, alert_type: str) -> bool:
    """Record that an alert was sent for this symbol/type."""
    return db.record_alert(symbol, alert_type)
