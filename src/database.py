"""
Database connection and initialization.
"""

import os
import ssl
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.ext.declarative import declarative_base

from .config import settings


def get_database_url() -> str:
    """Get and format the database URL for asyncpg."""
    db_url = settings.DATABASE_URL
    
    # Convert to asyncpg format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    
    return db_url


def get_connect_args() -> dict:
    """Get connection arguments, including SSL for production."""
    # Check if we're in production (Fly.io sets this)
    if settings.ENVIRONMENT == "production" or os.getenv("FLY_APP_NAME"):
        # Create SSL context that doesn't verify certificates (Fly.io internal)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return {"ssl": ssl_context}
    return {}


# Create async engine with proper SSL handling
engine = create_async_engine(
    get_database_url(),
    echo=settings.ENVIRONMENT == "development",
    connect_args=get_connect_args()
)

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
        # Import models to ensure they're registered
        from .models import Subscription, UsageLog, User

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close() 