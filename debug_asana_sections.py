
import asyncio
import sys
import os
import json
import logging

# Add the src directory to the python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from services.tool_executor import ToolExecutor
from database.connection import get_db

# Configure logging
logging.basicConfig(level=logging.INFO)

async def main():
    print("Initializing ToolExecutor...")
    # We need a valid user_id to get connections. Assuming a default or test user check connection logic
    # Actually ToolExecutor needs a user_id context. 
    # Let's check how ToolExecutor gets connections. It uses connection_service.
    
    # We might need to manually mock or setup the context if we are running standalone.
    # However, simpler: let's try to just instantiate direct service if possible, or use executor if it finds the connection in DB.
    # ToolExecutor methods usually take raw arguments. The connection lookup happens inside.
    # _execute_asana_list_tasks calls connection_service.get_connection_by_platform_user(user_id, 'asana')
    
    # I need to know the USER_ID the app uses. 
    # Usually it's in the auth context. 
    # Let's try to query the database for an active Asana connection first to get the user_id.

    from services.connection_service import ConnectionService
    
    executor = ToolExecutor()
    cs = ConnectionService()
    
    # Find a user with asana connection
    # Since I cannot easily query generic SQL here without setup, I'll try a common ID or list all.
    # But wait, I can just use the tool if I know the user_id.
    
    # Let's try to find an active connection directly from DB
    from models.connection import Connection
    from sqlalchemy import select
    
    conn_str = "sqlite:///./hub.db" # Assuming local sqlite for dev? Or checks environment.
    # better to rely on what the app uses.
    
    # Let's try 'user1' or similar if it's a dev env, or just list connections.
    async for db in get_db():
        result = await db.execute(select(Connection).where(Connection.platform == 'asana'))
        conn = result.scalars().first()
        if conn:
            print(f"Found Asana connection for user: {conn.user_id}")
            user_id = conn.user_id
            
            print("Executing asana_list_tasks...")
            # We need to simulate the tool execution context or just call the method if we can access it.
            # ToolExecutor._execute_asana_list_tasks is internal but we can call execute_tool
            
            # arguments
            args = {
                "limit": 10,
                "opt_fields": ["gid", "name", "completed", "due_on", "projects.name", "memberships.section.name"]
            }
            
            try:
                result = await executor.execute_tool("asana_list_tasks", args, user_id=user_id)
                print(json.dumps(result, indent=2))
            except Exception as e:
                print(f"Error executing tool: {e}")
                import traceback
                traceback.print_exc()
                
        else:
            print("No Asana connection found in database.")
        break # only need one session

if __name__ == "__main__":
    asyncio.run(main())
