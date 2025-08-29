"""
Database connection and initialization.
"""

import asyncio
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.ext.declarative import declarative_base

from .config import settings

# Create async engine with proper connection pool settings
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=settings.ENVIRONMENT == "development",
    # Connection pool settings to prevent connection leaks
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,  # Recycle connections every hour
    # Connection timeout settings
    connect_args={
        "command_timeout": 30,
        "server_settings": {
            "jit": "off",  # Disable JIT for faster connection
        }
    }
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
    """Get database session with proper transaction management."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            # Rollback transaction on any exception
            try:
                await session.rollback()
            except Exception as rollback_error:
                # Log rollback errors but don't raise them
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to rollback transaction: {rollback_error}")
            finally:
                # Re-raise original exception
                raise e
        finally:
            # Ensure session is properly closed
            try:
                await session.close()
            except Exception as close_error:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to close database session: {close_error}")


async def get_db_transaction() -> AsyncGenerator[AsyncSession, None]:
    """Get database session with automatic transaction management."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                # Transaction will be automatically rolled back by async with session.begin()
                raise


async def safe_db_operation(operation, session: AsyncSession, *args, **kwargs):
    """
    Safely execute a database operation with proper error handling.
    
    Args:
        operation: The database operation function to execute
        session: The database session
        *args, **kwargs: Arguments to pass to the operation
        
    Returns:
        The result of the operation
        
    Raises:
        The original exception if operation fails
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        result = await operation(session, *args, **kwargs)
        await session.commit()
        return result
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        try:
            await session.rollback()
            logger.info("Database transaction rolled back successfully")
        except Exception as rollback_error:
            logger.error(f"Failed to rollback transaction: {rollback_error}")
        raise e


class DatabaseTransaction:
    """Context manager for safe database transactions."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.committed = False
        
    async def __aenter__(self):
        return self
        
    async def commit(self):
        """Manually commit the transaction."""
        if not self.committed:
            await self.session.commit()
            self.committed = True
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        import logging
        logger = logging.getLogger(__name__)
        
        if exc_type is not None:
            # Exception occurred, rollback
            try:
                await self.session.rollback()
                logger.info("Transaction rolled back due to exception")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback transaction: {rollback_error}")
        elif not self.committed:
            # No exception but not committed, commit now
            try:
                await self.session.commit()
                self.committed = True
                logger.debug("Transaction committed successfully")
            except Exception as commit_error:
                logger.error(f"Failed to commit transaction: {commit_error}")
                try:
                    await self.session.rollback()
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback after commit error: {rollback_error}")
                raise commit_error 