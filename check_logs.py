import asyncio
from src.database import get_session_maker
from src.models import ObservabilityLog
from sqlalchemy import select

async def main():
    session_maker = get_session_maker()
    async with session_maker() as db:
        res = await db.execute(select(ObservabilityLog).order_by(ObservabilityLog.timestamp.desc()).limit(20))
        for r in res.scalars():
            print(f"[{r.level}] {r.message} | Payload: {r.payload}")

if __name__ == '__main__':
    asyncio.run(main())
