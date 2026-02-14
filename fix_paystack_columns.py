
import asyncio
import logging
from sqlalchemy import text
from src.database import get_engine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_paystack_columns():
    """
    Manually add missing Paystack columns to the users table.
    """
    engine = get_engine()
    
    async with engine.begin() as conn:
        logger.info("Checking for missing Paystack columns...")

        # Columns to add to 'users' table
        columns_to_add = [
            ("paystack_customer_code", "VARCHAR"),
            ("paystack_authorization_code", "VARCHAR")
        ]

        for col_name, col_def in columns_to_add:
            # Check if column exists
            query = text(f"""
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='{col_name}'
            """)
            result = await conn.execute(query)
            if not result.fetchone():
                logger.info(f"Adding column '{col_name}' to 'users' table...")
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
            else:
                logger.info(f"Column '{col_name}' already exists.")

        logger.info("✅ Paystack columns sync completed successfully.")

if __name__ == "__main__":
    asyncio.run(fix_paystack_columns())
