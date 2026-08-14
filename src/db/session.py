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

load_dotenv()

logger = logging.getLogger("ai_engineer.db")

def get_database_url() -> str:
    """
    Resolve the database URL from environment variables or fallback to SQLite.
    Normalizes 'postgres://' to 'postgresql://' for SQLAlchemy compatibility.
    """
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    
    if db_url:
        # Supabase and Heroku legacy connection strings use postgres://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return db_url
    
    # Default to local SQLite database in ./data/
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = data_dir / "ai_engineer.db"
    return f"sqlite:///{sqlite_path.as_posix()}"


DATABASE_URL = get_database_url()

# Engine configuration
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    # Production PostgreSQL / Supabase pool configuration
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """
    Initialize database schema (create all tables if they do not exist).
    """
    active_engine = target_engine or engine
    logger.info("Initializing database tables on engine: %s", active_engine.url)
    Base.metadata.create_all(bind=active_engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a thread-safe database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
