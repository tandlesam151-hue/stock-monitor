-- Stock monitor database bootstrap (idempotent where possible).
-- Run as the postgres superuser:
--   sudo -u postgres psql -f /mnt/d/my_chatbot/stock_monitor/db_setup.sql

-- 1. App role. Change the password after first setup.
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
