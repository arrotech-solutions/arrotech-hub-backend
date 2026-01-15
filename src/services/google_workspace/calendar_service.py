"""
Calendar Service for Google Workspace Integration
Handles calendar operations including events, meetings, and scheduling.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from .base_client import GoogleWorkspaceBaseClient


class CalendarService:
    """Service for Google Calendar operations"""
    
    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        self.service_name = 'calendar'
        self.version = 'v3'
    
    async def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        timezone: str = 'Africa/Nairobi',
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Create a calendar event
        
        Args:
            summary: Event title
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            description: Event description
            location: Event location
            attendees: List of attendee emails
            timezone: Timezone for the event
            calendar_id: Calendar ID (default 'primary')
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_time,
                    'timeZone': timezone
                },
                'end': {
                    'dateTime': end_time,
                    'timeZone': timezone
                }
            }
            
            if description:
                event['description'] = description
            if location:
                event['location'] = location
            if attendees:
                event['attendees'] = [{'email': email} for email in attendees]
            
            result = service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendUpdates='all' if attendees else 'none'
            ).execute()
            
            return {
                'success': True,
                'event_id': result.get('id'),
                'html_link': result.get('htmlLink'),
                'start': result.get('start'),
                'end': result.get('end')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 10,
        calendar_id: str = 'primary',
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List calendar events
        
        Args:
            time_min: Lower bound for event start time (ISO format)
            time_max: Upper bound for event start time (ISO format)
            max_results: Maximum number of events
            calendar_id: Calendar ID
            query: Free text search terms
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            params = {
                'calendarId': calendar_id,
                'maxResults': max_results,
                'singleEvents': True,
                'orderBy': 'startTime'
            }
            
            if time_min:
                params['timeMin'] = time_min
            if time_max:
                params['timeMax'] = time_max
            if query:
                params['q'] = query
            
            result = service.events().list(**params).execute()
            events = result.get('items', [])
            
            formatted_events = []
            for event in events:
                formatted_events.append({
                    'id': event.get('id'),
                    'summary': event.get('summary'),
                    'start': event.get('start', {}).get('dateTime', event.get('start', {}).get('date')),
                    'end': event.get('end', {}).get('dateTime', event.get('end', {}).get('date')),
                    'location': event.get('location'),
                    'description': event.get('description'),
                    'attendees': event.get('attendees', []),
                    'html_link': event.get('htmlLink')
                })
            
            return {
                'success': True,
                'events': formatted_events,
                'total': len(formatted_events)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Update an existing calendar event
        
        Args:
            event_id: Event ID to update
            summary: New event title
            start_time: New start time (ISO format)
            end_time: New end time (ISO format)
            description: New description
            location: New location
            calendar_id: Calendar ID
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            # Get existing event
            event = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Update fields
            if summary:
                event['summary'] = summary
            if start_time:
                event['start']['dateTime'] = start_time
            if end_time:
                event['end']['dateTime'] = end_time
            if description:
                event['description'] = description
            if location:
                event['location'] = location
            
            result = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendUpdates='all'
            ).execute()
            
            return {
                'success': True,
                'event_id': result.get('id'),
                'updated': result.get('updated')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = 'primary',
        send_updates: bool = True
    ) -> Dict[str, Any]:
        """
        Delete a calendar event
        
        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID
            send_updates: Send cancellation to attendees
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates='all' if send_updates else 'none'
            ).execute()
            
            return {
                'success': True,
                'event_id': event_id
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def check_availability(
        self,
        time_min: str,
        time_max: str,
        attendees: List[str],
        timezone: str = 'Africa/Nairobi'
    ) -> Dict[str, Any]:
        """
        Check availability of attendees during a time period
        
        Args:
            time_min: Start time (ISO format)
            time_max: End time (ISO format)
            attendees: List of attendee emails
            timezone: Timezone
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'timeMin': time_min,
                'timeMax': time_max,
                'timeZone': timezone,
                'items': [{'id': email} for email in attendees]
            }
            
            result = service.freebusy().query(body=body).execute()
            
            calendars = result.get('calendars', {})
            availability = {}
            
            for email, data in calendars.items():
                busy_periods = data.get('busy', [])
                availability[email] = {
                    'busy': busy_periods,
                    'available': len(busy_periods) == 0
                }
            
            return {
                'success': True,
                'availability': availability
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def create_meeting(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        attendees: List[str],
        description: Optional[str] = None,
        timezone: str = 'Africa/Nairobi'
    ) -> Dict[str, Any]:
        """
        Create a meeting with Google Meet link
        
        Args:
            summary: Meeting title
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            attendees: List of attendee emails
            description: Meeting description
            timezone: Timezone
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_time,
                    'timeZone': timezone
                },
                'end': {
                    'dateTime': end_time,
                    'timeZone': timezone
                },
                'attendees': [{'email': email} for email in attendees],
                'conferenceData': {
                    'createRequest': {
                        'requestId': f'meet-{datetime.now().timestamp()}',
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                }
            }
            
            if description:
                event['description'] = description
            
            result = service.events().insert(
                calendarId='primary',
                body=event,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            
            meet_link = result.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri')
            
            return {
                'success': True,
                'event_id': result.get('id'),
                'meet_link': meet_link,
                'html_link': result.get('htmlLink')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
