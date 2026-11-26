"""
Database Session & Connection Management (TASK-FS6)
Supports Supabase / PostgreSQL with automatic SQLite local fallback.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.db.models import Base
import src.db.benchmark_models  # noqa: F401

load_dotenv()

logger = logging.getLogger("ai_engineer.db")

def _normalize_db_url(raw_url: str) -> str:
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url


def get_database_url() -> str:
    """
    Resolve the database URL from environment variables or fallback to SQLite.
    Normalizes 'postgres://' to 'postgresql://' for SQLAlchemy compatibility.
    """
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if db_url:
        return _normalize_db_url(db_url)

    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = data_dir / "ai_engineer.db"
    return f"sqlite:///{sqlite_path.as_posix()}"


def get_benchmark_readonly_db_url() -> str:
    """Dedicated read-only DB role URL for the benchmark page (`benchmark_reader`)."""
    raw = os.getenv("BENCHMARK_READONLY_DATABASE_URL", "").strip()
    return _normalize_db_url(raw) if raw else get_database_url()


def get_benchmark_importer_db_url() -> str:
    """Dedicated writer DB role URL ONLY for the snapshot_importer CLI (`benchmark_importer`)."""
    raw = os.getenv("BENCHMARK_IMPORTER_DATABASE_URL", "").strip()
    return _normalize_db_url(raw) if raw else get_database_url()


DATABASE_URL = get_database_url()


def create_active_engine(db_url: str):
    """Create engine with SQLite fallback if remote DB is unreachable."""
    sqlite_opts = {"schema_translate_map": {"benchmark": None}}
    if db_url.startswith("sqlite"):
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            execution_options=sqlite_opts,
            echo=False,
        )
    try:
        remote_engine = create_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=False,
        )
        # Test connection immediately
        with remote_engine.connect():
            pass
        return remote_engine
    except Exception as err:
        logger.warning(
            "Remote database connection failed (%s). Falling back automatically to local SQLite.",
            err,
        )
        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        sqlite_path = data_dir / "ai_engineer.db"
        return create_engine(
            f"sqlite:///{sqlite_path.as_posix()}",
            connect_args={"check_same_thread": False},
            execution_options=sqlite_opts,
            echo=False,
        )


engine = create_active_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_read_url = get_benchmark_readonly_db_url()
benchmark_read_engine = engine if _read_url == DATABASE_URL else create_active_engine(_read_url)
BenchmarkReadSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=benchmark_read_engine)


def _migrate_benchmark_columns(target_engine) -> None:
    """Safely adds newly introduced benchmark columns to existing research_repos table if absent."""
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(target_engine)
        if "research_repos" not in inspector.get_table_names():
            return
        existing_cols = {col["name"] for col in inspector.get_columns("research_repos")}
        cols_to_add = [
            ("cve_id", "VARCHAR(50)"),
            ("user_cwe", "VARCHAR(50)"),
            ("repo_type", "VARCHAR(50) DEFAULT 'cve_fix'"),
            ("fix_commit", "VARCHAR(64)"),
            ("parent_commit", "VARCHAR(64)"),
            ("label_quality", "VARCHAR(20) DEFAULT 'provisional'"),
            ("is_excluded", "BOOLEAN DEFAULT 0"),
            ("exclusion_reason", "TEXT"),
            ("job_stage", "VARCHAR(50) DEFAULT 'done'"),
            ("job_progress", "FLOAT DEFAULT 1.0"),
            ("job_error", "TEXT"),
            ("last_heartbeat", "DATETIME"),
            ("ignored_candidates", "JSON DEFAULT '[]'"),
            ("scope_override", "JSON"),
        ]
        with target_engine.connect() as conn:
            for col_name, col_type in cols_to_add:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE research_repos ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
            if "benchmark_runs" in inspector.get_table_names():
                run_cols = {col["name"] for col in inspector.get_columns("benchmark_runs")}
                if "run_metadata" not in run_cols:
                    conn.execute(text("ALTER TABLE benchmark_runs ADD COLUMN run_metadata JSON DEFAULT '{}'"))
                    conn.commit()
                if "run_version" not in run_cols:
                    conn.execute(text("ALTER TABLE benchmark_runs ADD COLUMN run_version INTEGER DEFAULT 1"))
                    conn.commit()
                if "is_superseded" not in run_cols:
                    conn.execute(text("ALTER TABLE benchmark_runs ADD COLUMN is_superseded BOOLEAN DEFAULT 0"))
                    conn.commit()
            if "benchmark_metrics" in inspector.get_table_names():
                met_cols = {col["name"] for col in inspector.get_columns("benchmark_metrics")}
                if "run_version" not in met_cols:
                    conn.execute(text("ALTER TABLE benchmark_metrics ADD COLUMN run_version INTEGER DEFAULT 1"))
                    conn.commit()
                if "is_superseded" not in met_cols:
                    conn.execute(text("ALTER TABLE benchmark_metrics ADD COLUMN is_superseded BOOLEAN DEFAULT 0"))
                    conn.commit()
    except Exception as e:
        logger.debug("Benchmark column migration skipped or failed: %s", e)


def init_db(target_engine=None) -> None:
    """
    Initialize database schema (create all tables if they do not exist).
    """
    from sqlalchemy import text
    active_engine = target_engine or engine
    logger.info("Initializing database tables on engine: %s", active_engine.url)
    if active_engine.dialect.name == "postgresql":
        with active_engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS benchmark"))
    Base.metadata.create_all(bind=active_engine)
    _migrate_benchmark_columns(active_engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a thread-safe database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_benchmark_read_db() -> Generator[Session, None, None]:
    """
    Read-only DB dependency for benchmark read APIs.
    Uses BENCHMARK_READONLY_DATABASE_URL (benchmark_reader role) and enforces
    read-only transaction/connection mode at the driver level.
    """
    from sqlalchemy import text
    db = BenchmarkReadSessionLocal()
    try:
        dialect = db.bind.dialect.name if db.bind is not None else ""
        if dialect == "sqlite":
            db.execute(text("PRAGMA query_only = ON"))
        elif dialect == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        yield db
    finally:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            try:
                db.execute(text("PRAGMA query_only = OFF"))
            except Exception:
                pass
        db.close()


def get_benchmark_importer_session() -> tuple[Any, Session]:
    """
    Returns (importer_engine, session) using BENCHMARK_IMPORTER_DATABASE_URL
    (dedicated writer role ONLY for snapshot_importer CLI).
    """
    imp_url = get_benchmark_importer_db_url()
    imp_engine = engine if imp_url == DATABASE_URL else create_active_engine(imp_url)
    ImpSession = sessionmaker(autocommit=False, autoflush=False, bind=imp_engine)
    return imp_engine, ImpSession()
