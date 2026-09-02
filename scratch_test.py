import asyncio
from sqlalchemy import select, String, cast, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

async def test_search():
    from src.models import ObservabilityLog
    # Create query
    phone = "254711371265"
    q = select(ObservabilityLog).where(
        or_(
            cast(ObservabilityLog.payload, String).contains(phone),
            ObservabilityLog.error_message.contains(phone)
        )
    )
    print("COMPILED QUERY:")
    # Using postgresql dialect to compile
    from sqlalchemy.dialects import postgresql
    print(q.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

if __name__ == "__main__":
    asyncio.run(test_search())
