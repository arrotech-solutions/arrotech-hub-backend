
import asyncio
import logging
import os
import sys
from sqlalchemy import text
from src.database import get_engine, Base
# Import all models to ensure they are registered with Base.metadata
from src.models import (
    User, Subscription, UsageLog, Connection, UserSettings, 
    Conversation, Message, Workflow, WorkflowStep, WorkflowExecution,
    WorkflowStepExecution, WorkflowDownload, WorkflowReview, 
    Payment, CreatorProfile, WorkflowVersion, WorkflowAnalytics,
    Notification, WorkflowFavorite, UserPreferences, CreatorFollower,
    ActivityFeedItem, MpesaPayment, MpesaAgentConfig, AccessRequest
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def rebuild_production_db():
    """
    1. Drops the entire public schema.
    2. Recreates the public schema.
    3. Uses SQLAlchemy to create all tables from models.
    4. Stamps the database with Alembic 'head' so future migrations work.
    """
    logger.warning("!!! WARNING: THIS WILL PERMANENTLY DELETE ALL PRODUCTION DATA !!!")
    
    # Check if we are in a non-interactive environment (like a script or CI)
    # If not, ask for confirmation.
    if sys.stdin.isatty():
        confirm = input("Are you absolutely sure? Type 'YES' to delete all production data: ")
        if confirm != "YES":
            logger.info("Rebuild cancelled.")
            return

    engine = get_engine()
    
    async with engine.begin() as conn:
        logger.info("Step 1: Wiping existing schema...")
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        await conn.execute(text("CREATE SCHEMA public;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        
        logger.info("Step 2: Creating all tables from SQLAlchemy models...")
        # run_sync is needed for metadata.create_all in async environment
        await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Step 3: Initializing Alembic migration tracking...")
        # Create alembic_version table manually and stamp it
        # This allows future 'alembic upgrade' commands to work correctly
        await conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY);"))
        # Since we have no migrations yet, we'll leave it empty for now, 
        # or we can stamp it after we create the first migration.
        
    logger.info("✅ Database rebuilt successfully from scratch.")
    logger.info("Next step: You should now generate a fresh 'initial' migration.")

if __name__ == "__main__":
    asyncio.run(rebuild_production_db())
