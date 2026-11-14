-- MEDD Maharashtra 2.0 — one-time database + role bootstrap.
-- Run as the PostgreSQL superuser:   psql -U postgres -v app_pw="'...'" -v ro_pw="'...'" -f scripts/init_db.sql
-- (scripts/setup_database.py does this for you using the passwords in backend/.env.)
\set ON_ERROR_STOP on

SELECT 'CREATE ROLE medd_app LOGIN PASSWORD ' || :app_pw
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medd_app') \gexec
SELECT 'CREATE ROLE medd_readonly LOGIN PASSWORD ' || :ro_pw
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medd_readonly') \gexec

ALTER ROLE medd_app NOSUPERUSER NOCREATEROLE NOCREATEDB;
ALTER ROLE medd_readonly NOSUPERUSER NOCREATEROLE NOCREATEDB;
ALTER ROLE medd_readonly SET default_transaction_read_only = on;

SELECT 'CREATE DATABASE medd OWNER medd_app ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'medd') \gexec

\c medd
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE medd TO medd_readonly;
-- Future objects created by medd_app become readable by medd_readonly in analytical schemas
-- (schema-level grants are applied by the Alembic migration once schemas exist).
