import asyncio
import aiohttp
from src.database import get_session_maker
from src.models import Connection
from sqlalchemy import select

async def main():
    session_maker = get_session_maker()
    async with session_maker() as db:
        conn = await db.execute(select(Connection).where(Connection.platform == 'whatsapp').limit(1))
        c = conn.scalar_one_or_none()
        if not c:
            print('No connection')
            return
        
        config = c.config
        phone_id = config.get('phone_number_id')
        token = config.get('access_token')
        base_url = config.get('base_url', 'https://graph.facebook.com/v22.0')
        
        if not phone_id or not token:
            print('No credentials')
            return
        
        url = f'{base_url}/{phone_id}/messages'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        
        # Test with your own number or just a dummy one to see the error message
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': '254711371265', 
            'type': 'typing_indicator',
            'typing_indicator': {'action': 'typing_on'}
        }
        
        print("Sending typing indicator...")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                print(f"Status: {resp.status}")
                print(f"Response: {await resp.text()}")

if __name__ == '__main__':
    asyncio.run(main())
