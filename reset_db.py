
import asyncio
import logging
from sqlalchemy import text
from src.database import get_engine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def reset_production_db():
    """
    WARNING: THIS WILL DELETE ALL DATA IN THE DATABASE.
    It drops the public schema and recreates it.
    """
    logger.warning("!!! WARNING: RESETTING DATABASE. ALL DATA WILL BE LOST !!!")
    
    # Simple confirmation for script safety
    confirm = input("Are you absolutely sure you want to wipe the PRODUCTION database? (type 'YES'): ")
    if confirm != "YES":
        logger.info("Reset cancelled.")
        return

    engine = get_engine()
    
    async with engine.begin() as conn:
        logger.info("Dropping public schema...")
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        logger.info("Recreating public schema...")
        await conn.execute(text("CREATE SCHEMA public;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        await conn.execute(text("COMMENT ON SCHEMA public IS 'standard public schema';"))
        
    logger.info("✅ Database reset successfully. It is now completely empty.")

if __name__ == "__main__":
    asyncio.run(reset_production_db())
