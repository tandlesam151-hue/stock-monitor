-- Stock monitor database bootstrap (idempotent where possible).
--
-- Run as the postgres superuser from the project directory:
--   sudo -u postgres psql -f /data/github/stock-monitor/stock_monitor/db_setup.sql
--
-- This creates the app role, the database, and enables the TimescaleDB
-- extension inside it. The actual tables/hypertables (alerts, ohlcv, signals)
-- are created at runtime by db.init_schema() the first time the app or any
-- script connects, so they are intentionally NOT defined here.

-- 1. App role. Change the password after first setup, and set the same value
--    in the app's .env as DB_PASSWORD.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stockbot') THEN
        CREATE ROLE stockbot LOGIN PASSWORD 'stockbot_dev_pw';
    END IF;
END
$$;

-- 2. Database owned by the app role (CREATE DATABASE cannot run inside a
--    transaction/DO block, so it is guarded with \gexec instead).
SELECT 'CREATE DATABASE stock_monitor OWNER stockbot'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'stock_monitor')
\gexec

-- 3. Enable the TimescaleDB extension inside the app database. The ohlcv and
--    signals tables are promoted to hypertables by db.init_schema(), which
--    requires this extension to be present first.
\connect stock_monitor
CREATE EXTENSION IF NOT EXISTS timescaledb;
