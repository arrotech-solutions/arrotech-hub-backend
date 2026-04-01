
import asyncio
import os
import sys
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'arrotech-hub-backend', 'src'))

from services.google_workspace.docs_service import DocsService
from services.google_workspace.base_client import GoogleWorkspaceBaseClient

async def test_list_folders():
    # Mock base client
    mock_base_client = MagicMock(spec=GoogleWorkspaceBaseClient)
    mock_service = MagicMock()
    mock_base_client.get_service.return_value = mock_service
    
    # Mock drive service list results
    mock_list = mock_service.files().list
    mock_execute = mock_list.return_value.execute
    mock_execute.return_value = {
        'files': [
            {'id': 'id1', 'name': 'Folder 1'},
            {'id': 'id2', 'name': 'Folder 2'}
        ]
    }
    
    docs_service = DocsService(mock_base_client)
    result = await docs_service.list_folders()
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(test_list_folders())
