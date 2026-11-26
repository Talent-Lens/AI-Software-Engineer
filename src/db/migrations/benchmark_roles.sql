-- PostgreSQL / Supabase Schema & Least-Privilege Role Provisioning for Benchmarks
-- Run as a database superuser / schema owner during production deployment.

CREATE SCHEMA IF NOT EXISTS benchmark;

-- 1. Read-only role for the Benchmark UI / Read APIs (SELECT on benchmark.* only; no user-scan access)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'benchmark_reader') THEN
        CREATE ROLE benchmark_reader NOINHERIT LOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM benchmark_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM benchmark_reader;
GRANT USAGE ON SCHEMA benchmark TO benchmark_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA benchmark TO benchmark_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA benchmark GRANT SELECT ON TABLES TO benchmark_reader;

-- 2. Dedicated writer role ONLY for the snapshot_importer CLI (no access to user-scan tables in public)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'benchmark_importer') THEN
        CREATE ROLE benchmark_importer NOINHERIT LOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM benchmark_importer;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM benchmark_importer;
GRANT USAGE, CREATE ON SCHEMA benchmark TO benchmark_importer;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA benchmark TO benchmark_importer;
ALTER DEFAULT PRIVILEGES IN SCHEMA benchmark GRANT SELECT, INSERT, UPDATE ON TABLES TO benchmark_importer;
