
import asyncio
import logging
from sqlalchemy import text
from src.database import get_engine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_missing_columns():
    """
    Manually add missing columns to the workflows table and create necessary enums.
    This fixes the issue where Base.metadata.create_all doesn't update existing tables.
    """
    engine = get_engine()
    
    async with engine.begin() as conn:
        logger.info("Checking for missing database components...")

        # 1. Create Enums if they don't exist
        # PostgreSQL doesn't have "CREATE TYPE IF NOT EXISTS" in older versions, 
        # so we check in pg_type
        enums = [
            ("workflowvisibility", ["private", "unlisted", "public", "marketplace"]),
            ("workflowlicense", ["free", "personal", "commercial", "enterprise"])
        ]
        
        for enum_name, values in enums:
            result = await conn.execute(text(f"SELECT 1 FROM pg_type WHERE typname = '{enum_name}'"))
            if not result.fetchone():
                logger.info(f"Creating enum {enum_name}...")
                values_str = ", ".join([f"'{v}'" for v in values])
                await conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({values_str})"))
            else:
                logger.info(f"Enum {enum_name} already exists.")

        # 2. Check and add columns to 'workflows' table
        # We'll use a safer approach: check if column exists first
        columns_to_add = [
            ("visibility", "workflowvisibility DEFAULT 'private'"),
            ("share_code", "VARCHAR UNIQUE"),
            ("license_type", "workflowlicense DEFAULT 'free'"),
            ("price", "INTEGER"), # Using INTEGER for cents as in models.py
            ("currency", "VARCHAR DEFAULT 'USD'"),
            ("category", "VARCHAR"),
            ("tags", "JSON"),
            ("required_connections", "JSON"),
            ("downloads_count", "INTEGER DEFAULT 0"),
            ("rating_sum", "INTEGER DEFAULT 0"),
            ("rating_count", "INTEGER DEFAULT 0"),
            ("author_name", "VARCHAR"),
            ("preview_image", "VARCHAR")
        ]

        for col_name, col_def in columns_to_add:
            # Check if column exists
            query = text(f"""
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='workflows' AND column_name='{col_name}'
            """)
            result = await conn.execute(query)
            if not result.fetchone():
                logger.info(f"Adding column '{col_name}' to 'workflows' table...")
                await conn.execute(text(f"ALTER TABLE workflows ADD COLUMN {col_name} {col_def}"))
            else:
                logger.debug(f"Column '{col_name}' already exists.")

        # 3. Create missing tables if they don't exist (though create_all should handle these if they are new)
        # We'll let create_all handle new tables, but we can double check 'workflow_downloads' and 'workflow_reviews'
        
        # Finally, we should also check if the 'mpesa_payments' table has everything it needs 
        # since migration 008 might also be pending
        
        logger.info("✅ Database sync completed successfully.")

if __name__ == "__main__":
    asyncio.run(fix_missing_columns())
