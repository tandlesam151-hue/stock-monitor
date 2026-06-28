# Stock Monitor Setup Guide

Intraday NSE signal monitor. Every 5 minutes it fetches the latest session's
5-min OHLCV bars for each watchlist symbol, computes a weighted bull/bear
signal score, overlays daily-timeframe context (trend regime plus floor-pivot
support/resistance), and sends Discord/Telegram alerts on high-conviction
setups. Alerts carry both ATR-based and structure-based (pivot) stop/target
levels. Time-series data is persisted to PostgreSQL + TimescaleDB.

## Requirements

- Python 3.9+
- PostgreSQL 14+ with the **TimescaleDB** extension available
- Network access to Yahoo Finance (via `yfinance`)

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up the database** (creates the `stockbot` role, the `stock_monitor`
   database, and enables TimescaleDB):
   ```bash
   sudo -u postgres psql -f db_setup.sql
   ```
   Change the default role password in `db_setup.sql` before running it in any
   non-local environment, and use the same value for `DB_PASSWORD` below.

   The application tables (`alerts`, plus the `ohlcv` and `signals`
   hypertables) are created automatically at first run by `db.init_schema()` —
   you do not create them by hand.

   **First-time cluster bootstrap (RHEL/Rocky/Alma — skip if your cluster is
   already initialized and running).** On Debian/Ubuntu the cluster is created
   and started by the package install; on RHEL family it is not. There you must
   initialize, enable the TimescaleDB preload, allow password auth for local TCP
   connections, and start the service *before* running `db_setup.sql`:
   ```bash
   sudo /usr/bin/postgresql-setup --initdb                      # create the cluster
   # Enable the TimescaleDB shared library (required for CREATE EXTENSION):
   echo "shared_preload_libraries = 'timescaledb'" | sudo tee -a /var/lib/pgsql/data/postgresql.conf
   # Allow password (scram) auth on local TCP, which the app uses (DB_HOST=127.0.0.1).
   # The RHEL default is 'ident', which rejects the app's password login:
   sudo sed -i -E 's|^(host\s+all\s+all\s+127\.0\.0\.1/32\s+)ident|\1scram-sha-256|' /var/lib/pgsql/data/pg_hba.conf
   sudo sed -i -E 's|^(host\s+all\s+all\s+::1/128\s+)ident|\1scram-sha-256|'         /var/lib/pgsql/data/pg_hba.conf
   sudo systemctl enable --now postgresql                       # start + run on boot
   ```
   Ensure PostgreSQL auto-starts on boot (`systemctl enable postgresql`) so the
   cron-launched monitor can always reach it.

3. **Configure credentials and connection** via environment variables. Copy the
   template and edit it:
   ```bash
   cp .env.example .env
   ```
   `.env` keys:
   ```ini
   # Notifications
   TELEGRAM_TOKEN=your_bot_token          # optional
   TELEGRAM_CHAT_ID=your_chat_id          # optional
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

   # Timezone (defaults to Asia/Kolkata)
   TIMEZONE=Asia/Kolkata

   # PostgreSQL + TimescaleDB
   DB_HOST=127.0.0.1
   DB_PORT=5432
   DB_NAME=stock_monitor
   DB_USER=stockbot
   DB_PASSWORD=your_db_password

   # Persistence toggles (true/false)
   PERSIST_OHLCV=true
   PERSIST_SIGNALS=true

   # Market-hours gating (see "Market hours" below)
   ALLOW_ANYTIME=false
   ALLOW_WEEKEND_RUN=false
   ```
   Environment variables also work without a `.env` file (e.g. exported in the
   shell, or set by your process manager / container platform).

4. **(Optional) Backfill history** — load the last 30 days of 5-min bars into
   the `ohlcv` hypertable:
   ```bash
   python backfill_30d.py
   ```

5. **Run the monitor:**
   ```bash
   python main.py
   ```

## Running under cron (production)

The monitor is designed to run only during NSE trading hours. `monitor_ctl.sh`
starts/stops it and tracks the PID, and `/etc/cron.d/stock-monitor` drives the
schedule. Times in cron are UTC; the NSE window 09:00–15:30 IST maps to
03:30–10:00 UTC, Monday–Friday:

```cron
30 3 * * 1-5 root /data/github/stock-monitor/stock_monitor/monitor_ctl.sh start
0 10 * * 1-5 root /data/github/stock-monitor/stock_monitor/monitor_ctl.sh stop
```

Manual control:
```bash
./monitor_ctl.sh start   # launch main.py if not already running
./monitor_ctl.sh stop    # stop the running monitor
```
Logs are appended to `monitor.log`.

## Market hours

`main.py` has an in-app guard, `is_market_open()`, controlled by two settings
(read from the environment, see `config.py`):

- `ALLOW_ANYTIME` — when `true`, scans run regardless of time (useful for
  testing). Defaults to `false`.
- `ALLOW_WEEKEND_RUN` — when `true`, allows scans on Saturday/Sunday. Defaults
  to `false`.

In production both default to `false`, so the app self-limits to the
`MARKET_OPEN`–`MARKET_CLOSE` window on weekdays even if it is left running. For
ad-hoc testing outside market hours, set `ALLOW_ANYTIME=true` in `.env`.

## Configuration reference (`config.py`)

- `WATCHLIST` — NSE symbols to track (yfinance format: `SYMBOL.NS`).
- `ALERT_THRESHOLDS` — tuning knobs and the alert cooldown window.
- `MARKET_OPEN` / `MARKET_CLOSE` — trading-hours window (IST).
- `TIMEZONE` — defaults to `Asia/Kolkata`.
- `PERSIST_OHLCV` / `PERSIST_SIGNALS` — toggle time-series writes.
- `DB_*` — Postgres connection settings.

## Database

PostgreSQL + TimescaleDB. Three stores, created by `db.init_schema()`:

- `alerts` — alert-cooldown bookkeeping (regular table).
- `ohlcv` — 5-min OHLCV bars per symbol (hypertable, partitioned on `ts`).
- `signals` — scored analysis snapshot per scan (hypertable, partitioned on `ts`).

A legacy SQLite `monitor.db` is no longer used. If you are upgrading from the
old SQLite version, `migrate_sqlite.py` ports existing alert-cooldown rows into
Postgres.

## Validation & testing

```bash
python validate_syntax.py            # syntax check of core modules
python test_fetch_and_scoring.py     # deterministic fetch + scoring tests
python test_all.py                   # broader integration checks (hits Discord/yfinance)
python send_discord_test.py          # send a single test message to Discord
```

## Research: does the signal actually predict? (`ic_analysis.py` / `ic_model.py`)

Before trusting the alerts as a strategy, measure whether the signals have
predictive power. These tools are research-only — they never write to the
production DB (run with `PERSIST_OHLCV=false PERSIST_SIGNALS=false`).

```bash
# 1. Build a labeled dataset + edge report (replays the live engine, no lookahead).
#    --days 60 uses the maximum 5-min history Yahoo allows (~59 days).
PERSIST_OHLCV=false PERSIST_SIGNALS=false \
  python ic_analysis.py --days 60 --csv signal_labels.csv

# 2. Fit a regime-gated, out-of-sample logistic model and compare its IC to the
#    raw engine on the held-out test sessions.
python ic_model.py --csv signal_labels.csv
```

`ic_analysis.py` reports the Information Coefficient (IC), cross-sectional IC
information ratio, directional hit-rate, per-component edge and confidence
calibration. `ic_model.py` fits a calibrated logistic model (numpy only) on the
breakout/VWAP/volume components with a strict time-based train/test split and
prints a pass/fail verdict (bar: out-of-sample pooled IC > +0.03 **and**
IC IR > +0.3). The generated `signal_labels*.csv` files are git-ignored.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No module named 'yfinance'` / `psycopg` | `pip install -r requirements.txt` |
| `connection refused` / DB errors | Confirm Postgres is running and `DB_*` in `.env` are correct |
| `extension "timescaledb" is not available` | Install the TimescaleDB package for your Postgres version, then re-run `db_setup.sql` |
| `possibly delisted; no price data found` | Transient yfinance/Yahoo issue; the fetcher already falls back to the most recent available session |
| `5m data not available ... within the last 60 days` (research tools) | Yahoo caps 5-min history to ~60 days. Use `ic_analysis.py --days 60` (or less); longer windows are rejected outright |
| No alerts firing | Check it is within market hours (or set `ALLOW_ANYTIME=true`) and that signals are clearing `MIN_SCORE` |
| Discord alerts not working | Verify `DISCORD_WEBHOOK_URL` is a valid webhook URL |

## Files

- `main.py` — scheduler and scan loop
- `fetcher.py` — yfinance OHLCV fetch (latest-session slice)
- `indicators.py` — RSI, Bollinger, MACD, EMA, ATR, VWAP, volume ratio
- `patterns.py` — candlestick and breakout detection
- `context.py` — daily-timeframe context (no-lookahead): trend regime, prior-day
  and 20-day swing levels, floor pivots (R1/R2/S1/S2), daily ATR, avg volume
- `alert_engine.py` — scoring, daily-context confidence adjustment, ATR- and
  pivot-based levels, alert formatting, Discord embed
- `notifier.py` — Discord/Telegram delivery
- `db.py` — Postgres/TimescaleDB access layer and schema bootstrap
- `state.py` — alert-cooldown API (thin shim over `db.py`)
- `config.py` — configuration from environment
- `backfill_30d.py` — one-off 30-day OHLCV backfill
- `migrate_sqlite.py` — one-off SQLite→Postgres alert migration
- `ic_analysis.py` — research: replay the engine over history, label forward
  returns, and report IC / hit-rate / per-component edge / calibration
- `ic_model.py` — research: calibrated, regime-gated logistic model with an
  out-of-sample IC test vs the raw engine
- `monitor_ctl.sh` — start/stop control script for cron
