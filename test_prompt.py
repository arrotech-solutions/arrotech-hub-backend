import asyncio
import sys
import json
import os

# Add the project root to the python path
sys.path.append(r"d:\repos\hub\arrotech-hub-backend")

from src.database import SessionLocal
from src.services.tool_context_engine import tool_context_engine
from src.routers.chat_router import build_system_prompt

async def main():
    async with SessionLocal() as db:
        # User ID 1 is typically the primary developer user in local DBs
        user_id = 1
        relevant_tools = []
        user_query = "What can you do?"
        
        # 1. Test what tool context engine produces
        print("--- TOOL AWARENESS CONTEXT ---")
        tool_awareness_context = await tool_context_engine.build_tool_awareness_context(
            user_id, db, relevant_tools
        )
        print(tool_awareness_context)
        print("\n" + "="*50 + "\n")
        
        # 2. Test full system prompt
        print("--- FULL SYSTEM PROMPT ---")
        system_prompt = await build_system_prompt(
            relevant_tools,
            user_context={"tier": "Free", "connections": []},
            user_query=user_query,
            tool_awareness_context=tool_awareness_context
        )
        print(system_prompt)

if __name__ == "__main__":
    asyncio.run(main())
