"""
Sheets Service for Google Workspace Integration
Handles spreadsheet operations including reading, writing, and formatting.
"""
from typing import Dict, List, Any, Optional

from .base_client import GoogleWorkspaceBaseClient


class SheetsService:
    """Service for Google Sheets operations"""
    
    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        self.service_name = 'sheets'
        self.version = 'v4'
    
    async def create_spreadsheet(
        self,
        title: str,
        sheets: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a new spreadsheet
        
        Args:
            title: Spreadsheet title
            sheets: List of sheet names to create
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            spreadsheet_body = {
                'properties': {
                    'title': title
                }
            }
            
            if sheets:
                spreadsheet_body['sheets'] = [
                    {'properties': {'title': sheet_name}}
                    for sheet_name in sheets
                ]
            
            spreadsheet = service.spreadsheets().create(
                body=spreadsheet_body
            ).execute()
            
            return {
                'success': True,
                'spreadsheet_id': spreadsheet.get('spreadsheetId'),
                'spreadsheet_url': spreadsheet.get('spreadsheetUrl'),
                'title': title
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def read_range(
        self,
        spreadsheet_id: str,
        range_name: str
    ) -> Dict[str, Any]:
        """
        Read data from a spreadsheet range
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            range_name: Range in A1 notation (e.g., 'Sheet1!A1:D10')
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            
            return {
                'success': True,
                'range': result.get('range'),
                'values': values,
                'row_count': len(values),
                'column_count': len(values[0]) if values else 0
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def write_range(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        value_input_option: str = 'USER_ENTERED'
    ) -> Dict[str, Any]:
        """
        Write data to a spreadsheet range
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            range_name: Range in A1 notation
            values: 2D array of values to write
            value_input_option: 'RAW' or 'USER_ENTERED'
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'values': values
            }
            
            result = service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                body=body
            ).execute()
            
            return {
                'success': True,
                'updated_range': result.get('updatedRange'),
                'updated_rows': result.get('updatedRows'),
                'updated_columns': result.get('updatedColumns'),
                'updated_cells': result.get('updatedCells')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def append_rows(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        value_input_option: str = 'USER_ENTERED'
    ) -> Dict[str, Any]:
        """
        Append rows to a spreadsheet
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            range_name: Range in A1 notation
            values: 2D array of values to append
            value_input_option: 'RAW' or 'USER_ENTERED'
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'values': values
            }
            
            result = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            return {
                'success': True,
                'updated_range': result.get('updates', {}).get('updatedRange'),
                'updated_rows': result.get('updates', {}).get('updatedRows'),
                'updated_cells': result.get('updates', {}).get('updatedCells')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def clear_range(
        self,
        spreadsheet_id: str,
        range_name: str
    ) -> Dict[str, Any]:
        """
        Clear data from a range
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            range_name: Range in A1 notation
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            result = service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                body={}
            ).execute()
            
            return {
                'success': True,
                'cleared_range': result.get('clearedRange')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def batch_update(
        self,
        spreadsheet_id: str,
        requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute batch updates on a spreadsheet
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            requests: List of update requests
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'requests': requests
            }
            
            result = service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            return {
                'success': True,
                'spreadsheet_id': result.get('spreadsheetId'),
                'replies': result.get('replies', [])
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def format_cells(
        self,
        spreadsheet_id: str,
        range_name: str,
        format_options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply formatting to cells
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            range_name: Range in A1 notation
            format_options: Formatting options (backgroundColor, textFormat, etc.)
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            # Parse range to get sheet ID and range coordinates
            # This is a simplified version - production code would need proper parsing
            
            requests = [{
                'repeatCell': {
                    'range': {
                        'sheetId': 0,  # Would need to get actual sheet ID
                    },
                    'cell': {
                        'userEnteredFormat': format_options
                    },
                    'fields': 'userEnteredFormat'
                }
            }]
            
            return await self.batch_update(spreadsheet_id, requests)
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def create_chart(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        chart_type: str,
        data_range: str,
        position: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Create a chart in the spreadsheet
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            sheet_id: ID of the sheet
            chart_type: Type of chart (e.g., 'COLUMN', 'LINE', 'PIE')
            data_range: Range containing chart data
            position: Chart position with 'row' and 'column' keys
        """
        try:
            requests = [{
                'addChart': {
                    'chart': {
                        'spec': {
                            'title': 'Chart',
                            'basicChart': {
                                'chartType': chart_type,
                                'legendPosition': 'BOTTOM_LEGEND',
                                'axis': [],
                                'domains': [],
                                'series': []
                            }
                        },
                        'position': {
                            'overlayPosition': {
                                'anchorCell': {
                                    'sheetId': sheet_id,
                                    'rowIndex': position.get('row', 0),
                                    'columnIndex': position.get('column', 0)
                                }
                            }
                        }
                    }
                }
            }]
            
            return await self.batch_update(spreadsheet_id, requests)
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def get_spreadsheet_info(
        self,
        spreadsheet_id: str
    ) -> Dict[str, Any]:
        """
        Get spreadsheet metadata and information
        
        Args:
            spreadsheet_id: ID of the spreadsheet
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            
            sheets = []
            for sheet in spreadsheet.get('sheets', []):
                props = sheet.get('properties', {})
                sheets.append({
                    'title': props.get('title'),
                    'sheet_id': props.get('sheetId'),
                    'index': props.get('index'),
                    'row_count': props.get('gridProperties', {}).get('rowCount'),
                    'column_count': props.get('gridProperties', {}).get('columnCount')
                })
            
            return {
                'success': True,
                'spreadsheet_id': spreadsheet.get('spreadsheetId'),
                'title': spreadsheet.get('properties', {}).get('title'),
                'sheets': sheets,
                'spreadsheet_url': spreadsheet.get('spreadsheetUrl')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
