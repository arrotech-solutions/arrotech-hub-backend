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
        
        kwargs = {"echo": is_dev}
        
        # SQLite does not support these pool parameters
        if not db_url.startswith("sqlite"):
            kwargs.update({
                "pool_size": 5 if not is_dev else 10,
                "max_overflow": 10 if not is_dev else 20,
                "pool_timeout": 30,
                "pool_recycle": 1800,
                "pool_pre_ping": True,
            })
            
        _engine = create_async_engine(db_url, **kwargs)
    return _engine


# Create base class for models


# Create base class for models
Base = declarative_base()

# Metadata for migrations
metadata = MetaData()


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get the session factory."""
    return async_sessionmaker(
        get_engine(), class_=AsyncSession, expire_on_commit=False
    )


async def seed_admin_user():
    """Seed the admin user if configured."""
    from .config import settings
    # Only run if admin credentials are set
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return

    session_maker = get_session_maker()
    async with session_maker() as session:
        from sqlalchemy import select
        from .models import User
        from passlib.context import CryptContext
        
        # Check if admin user exists
        result = await session.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"[Admin] Seeding admin user: {settings.ADMIN_EMAIL}")
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            
            # Create strict admin user
            new_user = User(
                email=settings.ADMIN_EMAIL,
                name="System Admin",
                password_hash=pwd_context.hash(settings.ADMIN_PASSWORD),
                api_key="admin_" + os.urandom(12).hex(),
                # Assuming enterprise tier for admin
                subscription_tier="enterprise" 
            )
            session.add(new_user)
            await session.commit()
            print("[Admin] Admin user created.")


async def init_db():
    """Initialize database tables via Alembic and seed admin user."""
    # We no longer run Base.metadata.create_all here. Tables are managed by Alembic.
    
    # Import models to ensure they're registered with SQLAlchemy
    from .models import (Subscription, UsageLog, User, Organization, OrganizationMember, 
                          OrganizationInvitation, Department, AuditLogEntry, MessagingConversation,
                          ObservabilityLog, ObservabilityTrace, FailedEvent)  # noqa: F401

    # Seed admin user AFTER migrator has created tables
    try:
        await seed_admin_user()
    except Exception as e:
        print(f"[Admin] Error seeding admin user: {e}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
