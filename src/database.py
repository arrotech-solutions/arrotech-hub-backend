"""
Database connection and initialization.
"""

import os
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.ext.declarative import declarative_base


def get_database_url() -> str:
    """Get and format the database URL for asyncpg."""
    # Read directly from environment to ensure we get the actual value
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://user:pass@localhost/minihub"
    )

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


def create_engine():
    """Create the database engine."""
    db_url = get_database_url()
    is_dev = os.getenv("ENVIRONMENT", "development") == "development"

    return create_async_engine(
        db_url,
        echo=is_dev
    )


# Create async engine
engine = create_engine()

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Create base class for models
Base = declarative_base()

# Metadata for migrations
metadata = MetaData()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        # Import models to ensure they're registered with SQLAlchemy
        from .models import Subscription, UsageLog, User  # noqa: F401

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
