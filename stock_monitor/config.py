import os
from dotenv import load_dotenv

# Load environment variables from both the workspace root and package directory if present
load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)


def _get_env(name: str, default: str = "") -> str:
    """Read an environment variable and normalize quotes/whitespace."""
    value = os.getenv(name, default)
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


WATCHLIST = ["JUBLFOOD.NS", "HDFCBANK.NS", "IEX.NS", "CIPLA.NS", "SUNPHARMA.NS", "ITC.NS", "VEDL.NS",
             "EXIDEIND.NS", "HCLTECH.NS", "COALINDIA.NS", "WIPRO.NS", "NTPC.NS", "ONGC.NS", "RAYMOND.NS"]

ALERT_THRESHOLDS = {
    "pct_move"      : 1.5,   # alert if price moves ±1.5% from day open
    "candle_pct"    : 1.0,   # alert if 5-min candle body is ≥1%
    "cooldown_mins" : 30,    # don't repeat same alert within 30 min
}

MARKET_OPEN  = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE     = _get_env("TIMEZONE", "Asia/Kolkata")

# Read credentials from environment variables (safer for different environments)
TELEGRAM_TOKEN   = _get_env("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
DISCORD_WEBHOOK_URL = _get_env("DISCORD_WEBHOOK_URL", "YOUR_WEBHOOK_URL")


# --- PostgreSQL / TimescaleDB ----------------------------------------------
# Connection settings for the Postgres+TimescaleDB backend. Defaults match a
# local WSL install; override via .env for other environments.
DB_HOST     = _get_env("DB_HOST", "127.0.0.1")
DB_PORT     = _get_env("DB_PORT", "5432")
DB_NAME     = _get_env("DB_NAME", "stock_monitor")
DB_USER     = _get_env("DB_USER", "stockbot")
DB_PASSWORD = _get_env("DB_PASSWORD", "")


def _as_int(value: str, default: int) -> int:
    """Parse an int from the environment, falling back to ``default``."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: str, default: float) -> float:
    """Parse a float from the environment, falling back to ``default``."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


# --- DB resilience knobs ----------------------------------------------------
# A DB outage must never hang a scan or silence alerting. These bound how long
# the app waits on the database and how a circuit breaker behaves once it trips:
#   DB_CONNECT_TIMEOUT  - libpq TCP/connect timeout per new connection (seconds).
#   DB_POOL_TIMEOUT     - max time to wait for a pooled connection (seconds).
#   DB_BREAKER_COOLDOWN - after a failure trips the breaker, skip all DB work
#                         for this many seconds so subsequent calls in the same
#                         scan short-circuit instantly instead of each waiting
#                         out the timeout again.
DB_CONNECT_TIMEOUT  = _as_int(_get_env("DB_CONNECT_TIMEOUT", "3"), 3)
DB_POOL_TIMEOUT     = _as_float(_get_env("DB_POOL_TIMEOUT", "3"), 3.0)
DB_BREAKER_COOLDOWN = _as_int(_get_env("DB_BREAKER_COOLDOWN", "60"), 60)


def _as_bool(value: str, default: bool = True) -> bool:
    """Interpret common truthy/falsey string values from the environment."""
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- Market-hours gating ----------------------------------------------------
# main.py's is_market_open() guard. Production-safe defaults (False) mean the
# app only scans within the MARKET_OPEN-MARKET_CLOSE window on weekdays, even if
# left running. Override in .env for ad-hoc testing outside market hours:
#   ALLOW_ANYTIME=true      -> scan regardless of time of day
#   ALLOW_WEEKEND_RUN=true  -> allow scans on Saturday/Sunday
ALLOW_ANYTIME     = _as_bool(_get_env("ALLOW_ANYTIME", "false"), default=False)
ALLOW_WEEKEND_RUN = _as_bool(_get_env("ALLOW_WEEKEND_RUN", "false"), default=False)


# Persistence toggles: when enabled, every scan writes the 5-min OHLCV bars and
# the scored signal snapshot to TimescaleDB hypertables (builds history for
# later analysis/backtesting). Disable to run without writing time-series data.
PERSIST_OHLCV   = _as_bool(_get_env("PERSIST_OHLCV", "true"))
PERSIST_SIGNALS = _as_bool(_get_env("PERSIST_SIGNALS", "true"))


# --- Multi-timeframe daily context -----------------------------------------
# A higher-timeframe (daily) layer establishes trend regime and key levels so
# intraday 5-min signals can be filtered to only those that align with the
# bigger move ("don't fight the daily trend"). CONTEXT_DAILY_PERIOD is the
# yfinance period of daily bars to pull for that context (3mo gives enough
# history for a valid 50-day EMA). Set to "1mo" to use a shorter window.
# Daily bars barely change intraday, so the per-symbol context is cached and
# only refreshed every CONTEXT_TTL_SECONDS.
USE_DAILY_CONTEXT    = _as_bool(_get_env("USE_DAILY_CONTEXT", "true"))
CONTEXT_DAILY_PERIOD = _get_env("CONTEXT_DAILY_PERIOD", "3mo")
CONTEXT_TTL_SECONDS  = int(_get_env("CONTEXT_TTL_SECONDS", "3600"))


# --- yfinance fetch resilience ---------------------------------------------
# yfinance is flaky: it intermittently raises or returns an empty frame even
# for liquid symbols. Rather than silently dropping a symbol for the whole scan
# on the first hiccup, the fetcher retries with exponential backoff.
#   FETCH_MAX_ATTEMPTS - total attempts per fetch (1 = no retry).
#   FETCH_BACKOFF_BASE - base seconds for backoff; wait = base * 2**(attempt-1),
#                        so with base=0.5 the waits are 0.5s, 1.0s, 2.0s, ...
#   FETCH_BACKOFF_MAX  - cap on any single backoff sleep (seconds), to keep the
#                        per-symbol cost bounded within a 5-min scan budget.
FETCH_MAX_ATTEMPTS = _as_int(_get_env("FETCH_MAX_ATTEMPTS", "3"), 3)
FETCH_BACKOFF_BASE = _as_float(_get_env("FETCH_BACKOFF_BASE", "0.5"), 0.5)
FETCH_BACKOFF_MAX  = _as_float(_get_env("FETCH_BACKOFF_MAX", "8"), 8.0)