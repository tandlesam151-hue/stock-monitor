# Quick Start

Get the stock monitor running in a few steps. See `SETUP.md` for full detail.

## 1. Install dependencies
```bash
pip install -r requirements.txt
```

## 2. Set up the database (Postgres + TimescaleDB)
```bash
sudo -u postgres psql -f db_setup.sql
```
Creates the `stockbot` role, the `stock_monitor` database, and enables
TimescaleDB. App tables/hypertables are created automatically on first run.

## 3. Configure
```bash
cp .env.example .env
# edit .env: DISCORD_WEBHOOK_URL, DB_PASSWORD, (optional) Telegram creds
```

## 4. Run
```bash
python main.py
```
Outside market hours, set `ALLOW_ANYTIME=true` in `.env` to force scans for
testing.

## 5. Verify
```bash
python test_fetch_and_scoring.py   # deterministic fetch + scoring tests
python -c "import db; db.init_schema(); print('DB OK')"
```

## Production (cron)

Market-hours scheduling is handled by `monitor_ctl.sh` + `/etc/cron.d/stock-monitor`
(NSE 09:00–15:30 IST = 03:30–10:00 UTC, Mon–Fri):
```bash
./monitor_ctl.sh start   # launch if not running
./monitor_ctl.sh stop    # stop
tail -f monitor.log      # watch output
```

## Configuration via environment

All settings are read from environment variables (`.env` file or exported), so
the same code runs unchanged across dev/test/prod, containers, and cloud hosts.

| Variable | Purpose |
|----------|---------|
| `DISCORD_WEBHOOK_URL` | Discord alert destination |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | optional Telegram alerts |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Postgres connection |
| `TIMEZONE` | defaults to `Asia/Kolkata` |
| `PERSIST_OHLCV` / `PERSIST_SIGNALS` | toggle time-series writes |
| `ALLOW_ANYTIME` / `ALLOW_WEEKEND_RUN` | market-hours gating (default `false`) |

## Troubleshooting

| Error | Solution |
|-------|----------|
| `No module named 'dotenv'` / `psycopg` | `pip install -r requirements.txt` |
| `connection refused` | Ensure Postgres is running and `DB_*` are correct |
| `extension "timescaledb" is not available` | Install TimescaleDB for your Postgres version, re-run `db_setup.sql` |
| `Discord notification failed` | Check `DISCORD_WEBHOOK_URL` is a valid webhook |
| No alerts | Confirm market hours (or `ALLOW_ANYTIME=true`) and that scores clear `MIN_SCORE` |
