import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "").replace("postgres:5432", "localhost:5432")

from src.database import get_session_maker
from sqlalchemy import select
from src.models import Connection

async def check():
    session_maker = get_session_maker()
    async with session_maker() as db:
        stmt = select(Connection).where(Connection.platform == 'github')
        result = await db.execute(stmt)
        connections = result.scalars().all()
        for c in connections:
            token = c.config.get('access_token')
            print(f"User: {c.user_id}, Status: {c.status}, Token starts with: {token[:4] if token else None}, Token length: {len(token) if token else 0}")
            
            # Try validating the token against github API
            import httpx
            headers = {"Authorization": f"Bearer {token}", "User-Agent": "ArrotechHub"}
            resp = httpx.get("https://api.github.com/user", headers=headers)
            print(f"Token validation status: {resp.status_code}")
            if resp.status_code == 200:
                print(f"User: {resp.json().get('login')}")
            else:
                print(f"Error: {resp.text}")

            resp2 = httpx.get("https://api.github.com/repos/arrotech-solutions/arrotech-hub-backend", headers=headers)
            print(f"Repo access status: {resp2.status_code}")
            if resp2.status_code != 200:
                print(f"Repo access error: {resp2.text}")
                
asyncio.run(check())
