import asyncio
import uuid
from src.services.tool_executor import tool_executor
from src.database import get_session_maker
from src.models import User, SubscriptionTier

async def test_maps_tool_execution():
    print("🚀 Starting Maps Capability Layer Test...")
    
    # 1. Setup a mock user
    user = User(
        id=uuid.uuid4(),
        email="test@arrotech.com",
        subscription_tier=SubscriptionTier.PRO
    )
    
    # 2. Define the tool call we want to test
    # This simulates an agent trying to track an order for a customer
    tool_name = "maps.track_order_live"
    arguments = {
        "entity_id": "ORDER-99",
        "source": {
            "type": "api",
            "config": {"url": "https://mock.api/track"}
        },
        "destination": {"lat": -1.286389, "lng": 36.817223} # Nairobi
    }
    
    print(f"📦 Simulating agent tool call: {tool_name}")
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # 3. Execute the tool via the real ToolExecutor
            result = await tool_executor.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                user=user,
                db=db
            )
            
            print("\n✅ Execution Result:")
            import json
            print(json.dumps(result, indent=2))
            
            if result.get("success"):
                print("\n✨ SUCCESS: The plumbing is working!")
                print(f"💬 Conversational Message: {result['result'].get('message')}")
            else:
                print(f"\n❌ FAILED: {result.get('error')}")
                
        except Exception as e:
            print(f"\n💥 CRITICAL ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_maps_tool_execution())
