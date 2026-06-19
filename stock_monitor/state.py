import sqlite3
import time
import logging
import os

logger = logging.getLogger(__name__)
# Use absolute path to ensure database is always in the same location
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.db")

def _needs_migration(con) -> bool:
    """Return True if an 'alerts' table exists but has no primary key.

    Legacy databases created the table without a (symbol, alert_type) primary
    key, which let INSERT OR REPLACE append duplicate rows and corrupted the
    cooldown logic. Detect that case so init_db can rebuild the table.
    """
    exists = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
    ).fetchone()
    if not exists:
        return False
    # pk > 0 indicates the column participates in the primary key.
    has_pk = any(col[5] > 0 for col in con.execute("PRAGMA table_info(alerts)"))
    return not has_pk


def init_db():
    """Initialize SQLite database for alert tracking (with legacy migration)."""
    try:
        with sqlite3.connect(DB) as con:
            if _needs_migration(con):
                logger.info("Migrating legacy 'alerts' table to keyed schema")
                con.execute("""
                    CREATE TABLE alerts_new (
                        symbol TEXT, alert_type TEXT, last_sent REAL,
                        PRIMARY KEY (symbol, alert_type)
                    )""")
                # Collapse duplicates, keeping the most recent timestamp.
                con.execute("""
                    INSERT INTO alerts_new (symbol, alert_type, last_sent)
                    SELECT symbol, alert_type, MAX(last_sent)
                    FROM alerts GROUP BY symbol, alert_type""")
                con.execute("DROP TABLE alerts")
                con.execute("ALTER TABLE alerts_new RENAME TO alerts")
            else:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS alerts (
                        symbol TEXT, alert_type TEXT, last_sent REAL,
                        PRIMARY KEY (symbol, alert_type)
                    )""")
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_symbol_type "
                "ON alerts (symbol, alert_type)")
        logger.info(f"Database initialized: {os.path.abspath(DB)}")
    except Exception as e:
        logger.error(f"Database init error: {e}")

def can_alert(symbol: str, alert_type: str, cooldown_mins: int) -> bool:
    """Check if enough time has passed since last alert for this symbol/type."""
    try:
        with sqlite3.connect(DB) as con:
            row = con.execute(
                "SELECT last_sent FROM alerts WHERE symbol=? AND alert_type=?",
                (symbol, alert_type)).fetchone()

        if not row:
            return True

        elapsed_mins = (time.time() - row[0]) / 60
        return elapsed_mins > cooldown_mins
    except Exception as e:
        logger.error(f"can_alert error: {e}")
        return False

def record_alert(symbol: str, alert_type: str) -> bool:
    """Record when an alert was sent."""
    try:
        with sqlite3.connect(DB) as con:
            con.execute(
                "INSERT OR REPLACE INTO alerts VALUES (?,?,?)",
                (symbol, alert_type, time.time()))
        return True
    except Exception as e:
        logger.error(f"record_alert error: {e}")
        return False