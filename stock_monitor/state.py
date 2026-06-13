import sqlite3
import time
import logging
import os

logger = logging.getLogger(__name__)
# Use absolute path to ensure database is always in the same location
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.db")

def init_db():
    """Initialize SQLite database for alert tracking."""
    try:
        con = sqlite3.connect(DB)
        con.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                symbol TEXT, alert_type TEXT, last_sent REAL
            )""")
        con.commit()
        con.close()
        logger.info(f"Database initialized: {os.path.abspath(DB)}")
    except Exception as e:
        logger.error(f"Database init error: {e}")

def can_alert(symbol: str, alert_type: str, cooldown_mins: int) -> bool:
    """Check if enough time has passed since last alert for this symbol/type."""
    try:
        con = sqlite3.connect(DB)
        row = con.execute(
            "SELECT last_sent FROM alerts WHERE symbol=? AND alert_type=?",
            (symbol, alert_type)).fetchone()
        con.close()
        
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
        con = sqlite3.connect(DB)
        con.execute(
            "INSERT OR REPLACE INTO alerts VALUES (?,?,?)",
            (symbol, alert_type, time.time()))
        con.commit()
        con.close()
        return True
    except Exception as e:
        logger.error(f"record_alert error: {e}")
        return False