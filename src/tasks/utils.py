import asyncio

_worker_loop = None

def run_async(coro):
    """
    Helper to run an async coroutine in a sync Celery task.
    Uses a single persistent event loop per worker process to prevent
    SQLAlchemy asyncpg "attached to a different loop" errors.
    """
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    
    return _worker_loop.run_until_complete(coro)
