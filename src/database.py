"""
Database connection and initialization.
"""

import os
from typing import AsyncGenerator, Optional

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.ext.declarative import declarative_base

# Global engine - lazily initialized
_engine: Optional[AsyncEngine] = None


def get_database_url() -> str:
    """Get and format the database URL for asyncpg."""
    # Read directly from environment to ensure we get the actual value
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://user:pass@localhost/minihub"
    )

    # Log the URL for debugging (without password)
    safe_url = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"[Database] Connecting to: {safe_url}")

    # Convert to asyncpg format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    # Remove sslmode parameter - asyncpg doesn't support it in URL
    # We'll handle SSL via connect_args instead
    if "?sslmode=" in db_url:
        db_url = db_url.split("?sslmode=")[0]
    elif "&sslmode=" in db_url:
        # Handle case where sslmode is not the first parameter
        parts = db_url.split("&sslmode=")
        if len(parts) > 1:
            # Remove sslmode and its value, keep other params
            remainder = parts[1].split("&", 1)
            if len(remainder) > 1:
                db_url = parts[0] + "&" + remainder[1]
            else:
                db_url = parts[0]

    return db_url


def get_engine() -> AsyncEngine:
    """Get or create the database engine (lazy initialization)."""
    global _engine
    if _engine is None:
        db_url = get_database_url()
        is_dev = os.getenv("ENVIRONMENT", "development") == "development"
        _engine = create_async_engine(
            db_url,
            echo=is_dev
        )
    return _engine


# Property-like access to engine
@property
def engine() -> AsyncEngine:
    return get_engine()


# Create base class for models
Base = declarative_base()

# Metadata for migrations
metadata = MetaData()


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get the session factory."""
    return async_sessionmaker(
        get_engine(), class_=AsyncSession, expire_on_commit=False
    )


async def init_db():
    """Initialize database tables."""
    eng = get_engine()
    async with eng.begin() as conn:
        # Import models to ensure they're registered with SQLAlchemy
        from .models import Subscription, UsageLog, User  # noqa: F401

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
