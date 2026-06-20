"""One-time migration of existing alert-cooldown rows from the legacy SQLite
``monitor.db`` into the Postgres ``alerts`` table.

The SQLite schema stored ``last_sent`` as epoch seconds (REAL). Postgres stores
it as TIMESTAMPTZ, so each value is converted with ``to_timestamp``. Rows are
upserted, so the script is safe to run more than once.

Usage (from the project directory):
    python migrate_sqlite.py
    python migrate_sqlite.py --sqlite /path/to/monitor.db
"""

import argparse
import logging
import os
import sqlite3

import db

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("migrate_sqlite")

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.db")


def read_sqlite_alerts(path: str):
    """Return list of (symbol, alert_type, last_sent_epoch) from the SQLite db."""
    if not os.path.exists(path):
        logger.warning(f"SQLite file not found: {path} (nothing to migrate)")
        return []
    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "alerts" not in tables:
            logger.warning("No 'alerts' table in SQLite db (nothing to migrate)")
            return []
        rows = con.execute(
            "SELECT symbol, alert_type, last_sent FROM alerts"
        ).fetchall()
        return rows
    finally:
        con.close()


def migrate(rows) -> int:
    """Upsert rows into Postgres, converting epoch seconds to TIMESTAMPTZ."""
    if not rows:
        return 0
    db.init_schema()
    migrated = 0
    with db.connection() as conn:
        for symbol, alert_type, last_sent in rows:
            if symbol is None or alert_type is None or last_sent is None:
                logger.warning(f"Skipping incomplete row: {(symbol, alert_type, last_sent)}")
                continue
            conn.execute(
                "INSERT INTO alerts (symbol, alert_type, last_sent) "
                "VALUES (%s, %s, to_timestamp(%s)) "
                "ON CONFLICT (symbol, alert_type) "
                "DO UPDATE SET last_sent = EXCLUDED.last_sent",
                (symbol, alert_type, float(last_sent)),
            )
            migrated += 1
    return migrated


def main():
    parser = argparse.ArgumentParser(description="Migrate alerts from SQLite to Postgres")
    parser.add_argument("--sqlite", default=DEFAULT_DB, help="Path to monitor.db")
    args = parser.parse_args()

    rows = read_sqlite_alerts(args.sqlite)
    logger.info(f"Found {len(rows)} alert row(s) in {args.sqlite}")
    migrated = migrate(rows)
    logger.info(f"Migrated {migrated} alert row(s) into Postgres")

    # Show the resulting table contents for confirmation.
    try:
        with db.connection() as conn:
            result = conn.execute(
                "SELECT symbol, alert_type, last_sent FROM alerts ORDER BY symbol, alert_type"
            ).fetchall()
        logger.info(f"alerts table now has {len(result)} row(s):")
        for r in result:
            logger.info(f"  {r[0]} | {r[1]} | {r[2]}")
    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
