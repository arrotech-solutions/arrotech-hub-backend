import asyncio
from fastapi import FastAPI, APIRouter

app = FastAPI()

r1 = APIRouter()
r2 = APIRouter()

r1.include_router(r2)
app.include_router(r1)
app.include_router(r2)

async def main():
    async with app.router.lifespan_context(app):
        print("OK")

asyncio.run(main())
