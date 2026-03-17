# Imports
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import User, Connection, ConnectionStatus
from ..routers.auth_router import get_current_user
from ..services.tool_executor import tool_executor
from ..services.llm_service import llm_service

router = APIRouter(prefix="/ai", tags=["AI Features"])

class MorningBriefingResponse(BaseModel):
    greeting: str
    headline: str
    summary: str
    time_context: str = "day"  # "morning", "afternoon", "evening", "night"
    priorities: List[str]
    urgent_emails: Optional[List[Dict[str, str]]] = None
    risks: List[str]
    suggested_actions: List[Dict[str, str]]
    # Enhanced Fields for Phase 2
    calendar_events: Optional[List[Dict[str, Any]]] = None
    conversations: Optional[List[Dict[str, Any]]] = None
    weekly_pulse: Optional[Dict[str, Any]] = None

# Alias for backward compatibility
BriefingResponse = MorningBriefingResponse

def get_time_context() -> tuple[str, str]:
    """Returns (time_context, greeting_prefix) based on current hour."""
    from datetime import datetime
    hour = datetime.now().hour
    if hour < 12:
        return "morning", "Good morning"
    elif hour < 17:
        return "afternoon", "Good afternoon"
    elif hour < 21:
        return "evening", "Good evening"
    else:
        return "night", "Good night"

@router.get("/my-briefing", response_model=BriefingResponse)
@router.get("/morning-briefing", response_model=BriefingResponse, include_in_schema=False)  # Backward compat
async def get_my_briefing(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates a personalized briefing using REAL data from connected tools.
    Aggregates Calendar, Tasks, and Emails, then uses LLM to summarize.
    Time-aware greeting based on current time of day.
    """
    logging.info(f"Generating briefing for user {user.id}")
    
    # Get time context
    time_context, greeting_prefix = get_time_context()
    
    # 1. Fetch Context Data from Tools
    context_text = ""
    has_real_data = False
    
    # Data storage for structured response
    raw_calendar_events = []
    
    try:
        # Get active connections
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user.id, 
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connections = result.scalars().all()
        active_platforms = [c.platform for c in connections]
        
        logging.info(f"Active platforms found: {active_platforms}")
        
        # --- Calendar Events (Google) ---
        if "google_workspace" in active_platforms:
            now = datetime.now()
            time_min = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
            time_max = now.replace(hour=23, minute=59, second=59).isoformat() + "Z"
            
            cal_res = await tool_executor.execute_tool(
                tool_name="google_workspace_calendar", 
                arguments={"operation": "list_events", "time_min": time_min, "time_max": time_max, "max_results": 10},
                user=user, 
                db=db
            )
            logging.info(f"Calendar API Response keys: {cal_res.keys() if isinstance(cal_res, dict) else 'not a dict'}")
            
            # Robust event extraction - try multiple paths
            events = []
            if cal_res.get("success"):
                events = cal_res.get("data", {}).get("items", [])
            if not events:
                # Try alternative paths
                events = cal_res.get("events", [])
            if not events:
                result_data = cal_res.get("result", {})
                if isinstance(result_data, dict):
                    events = result_data.get("events", []) or result_data.get("items", [])
                elif isinstance(result_data, list):
                    events = result_data
            if not events:
                # Direct items path
                events = cal_res.get("items", [])
            
            logging.info(f"Calendar events found: {len(events)}")
            if events:
                has_real_data = True
                context_text += f"\nTODAY'S CALENDAR ({len(events)} events):\n"
                
                for idx, e in enumerate(events):
                    start = e.get("start", {}).get("dateTime", "All Day")
                    end = e.get("end", {}).get("dateTime", "")
                    summary = e.get("summary", "No Title")
                    location = e.get("location", "")
                    meet_link = e.get("hangoutLink", "")
                    
                    context_text += f"- {start}: {summary}\n"
                    
                    # Format for frontend structured data
                    # Parse time to nicer format
                    try:
                        start_time_obj = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        start_str = start_time_obj.strftime("%I:%M %p")
                        
                        end_str = ""
                        if end:
                            end_time_obj = datetime.fromisoformat(end.replace('Z', '+00:00'))
                            end_str = end_time_obj.strftime("%I:%M %p")
                            
                        is_now = start_time_obj <= datetime.now(start_time_obj.tzinfo) <= end_time_obj if end else False
                    except:
                        start_str = start
                        end_str = ""
                        is_now = False

                    raw_calendar_events.append({
                        "id": f"evt-{idx}",
                        "title": summary,
                        "startTime": start_str,
                        "endTime": end_str,
                        "isNow": is_now,
                        "location": location,
                        "meetingLink": meet_link
                    })

        # --- Tasks (Jira) ---
        if "jira" in active_platforms:
            jira_res = await tool_executor.execute_tool(
                tool_name="jira_issue_tracking",
                # Broader JQL: Show all my open work (To Do + In Progress), not just In Progress
                arguments={"action": "search_issues", "jql": "assignee = currentUser() AND statusCategory != Done order by updated DESC"},
                user=user,
                db=db
            )
            if jira_res.get("success"):
                issues = jira_res.get("data", {}).get("issues", [])
                if issues:
                    has_real_data = True
                    context_text += f"\nACTIVE JIRA ISSUES ({len(issues)}):\n"
                    # Limit to 5
                    for i in issues[:5]:
                        key = i.get("key")
                        summary = i.get("fields", {}).get("summary")
                        status = i.get("fields", {}).get("status", {}).get("name", "Unknown")
                        context_text += f"- [{key}] {summary} ({status})\n"

        # --- Tasks (ClickUp) ---
        if "clickup" in active_platforms:
            try:
                logging.info(f"[{datetime.now().isoformat()}] Fetching ClickUp...")
                
                # FIX: Ensure user is an object for tool_executor access to .subscription_tier
                from types import SimpleNamespace
                clickup_user = user
                if isinstance(user, dict):
                     # Create an object wrapper
                     clickup_user = SimpleNamespace(**user)
                     # Ensure subscription_tier exists if missing
                     if not hasattr(clickup_user, 'subscription_tier'):
                         clickup_user.subscription_tier = 'free' # default
                else:
                    # If it's a model but somehow missing the attr (unlikely), safe default?
                     if not hasattr(clickup_user, 'subscription_tier'):
                          clickup_user.subscription_tier = 'free'

                # First get teams
                teams_res = await tool_executor.execute_tool(
                    tool_name='clickup_task_management',
                    arguments={"operation": "get_teams"},
                    user=clickup_user,
                    db=db
                )
                
                # Robust team extraction
                teams = teams_res.get('teams', [])
                if not teams and 'data' in teams_res:
                    teams = teams_res['data'].get('teams', [])
                if not teams and 'result' in teams_res:
                        # Check result.teams or result.data.teams
                    if 'teams' in teams_res['result']:
                        teams = teams_res['result']['teams']
                    elif 'data' in teams_res['result']:
                        teams = teams_res['result']['data'].get('teams', [])

                if teams:
                    team_id = teams[0]['id']
                    logging.info(f"[{datetime.now().isoformat()}] Fetching ClickUp tasks for team {team_id}...")
                    
                    # Fetch ALL tasks (include_closed=True) to match frontend reliability, then filter manually
                    clickup_res = await tool_executor.execute_tool(
                        tool_name='clickup_task_management',
                        arguments={"operation": "get_team_tasks", "team_id": team_id, "include_closed": True},
                        user=clickup_user,
                        db=db
                    )
                    logging.info(f"[{datetime.now().isoformat()}] ClickUp Response Keys: {clickup_res.keys()}")
                    
                    # Robust task extraction
                    tasks = clickup_res.get('tasks', [])
                    if not tasks and 'data' in clickup_res:
                        tasks = clickup_res['data'].get('tasks', [])
                    if not tasks and 'result' in clickup_res:
                        if 'tasks' in clickup_res['result']:
                            tasks = clickup_res['result']['tasks']
                        elif 'data' in clickup_res['result']:
                            tasks = clickup_res['result']['data'].get('tasks', [])

                    logging.info(f"[{datetime.now().isoformat()}] ClickUp Tasks Found (Raw): {len(tasks)}")
                    
                    if tasks:
                        # manually filter for active tasks
                        active_tasks = []
                        for t in tasks:
                            # Robust status extraction for filtering
                            s_obj = t.get('status')
                            if isinstance(s_obj, dict):
                                status = s_obj.get('status', 'unknown')
                            elif isinstance(s_obj, str):
                                status = s_obj
                            else:
                                status = 'unknown'
                            
                            status = status.lower()
                            # Check if it looks like a done status (substring match like frontend)
                            is_done = 'complete' in status or 'closed' in status or 'done' in status
                            if not is_done:
                                active_tasks.append(t)
                        
                        if active_tasks:
                            has_real_data = True
                            context_text += f"\nACTIVE CLICKUP TASKS ({len(active_tasks)}):\n"
                            for t in active_tasks[:5]: # Limit to 5
                                s_obj = t.get('status')
                                if isinstance(s_obj, dict):
                                    status = s_obj.get('status', 'unknown')
                                elif isinstance(s_obj, str):
                                    status = s_obj
                                else:
                                    status = 'unknown'
                                
                                name = t.get('name', 'Task')
                                # Explicitly tag source for LLM
                                context_text += f"- [ClickUp] [{status}] {name}\n"
            except Exception as e:
                logging.error(f"[{datetime.now().isoformat()}] ClickUp Error: {e}")

        # --- Tasks (Trello) ---
        if "trello" in active_platforms:
            try:
                logging.info(f"[{datetime.now().isoformat()}] Fetching Trello...")
                # Use 'is:open' to match frontend logic
                trello_res = await tool_executor._execute_trello_tool('trello_project_management', {"action": "search_cards", "query": "is:open"}, user, db)
                logging.info(f"[{datetime.now().isoformat()}] Trello Response Keys: {trello_res.keys()}")
                
                # Handle potential nested structures
                cards = trello_res.get('cards', [])
                if not cards and 'data' in trello_res:
                    cards = trello_res['data'].get('cards', [])
                if not cards and 'result' in trello_res:
                    res_data = trello_res['result'].get('data', {})
                    cards = res_data.get('cards', [])
                    
                logging.info(f"[{datetime.now().isoformat()}] Trello Cards Found: {len(cards)}")
                
                if cards:
                    has_real_data = True
                    context_text += f"\nACTIVE TRELLO CARDS ({len(cards)}):\n"
                    for c in cards[:5]:
                        context_text += f"- {c.get('name')} (in {c.get('list', {}).get('name', 'List')})\n"
            except Exception as e:
                logging.error(f"[{datetime.now().isoformat()}] Trello Error: {e}")

        # --- Tasks (Asana) ---
        if "asana" in active_platforms:
            try:
                logging.info(f"[{datetime.now().isoformat()}] Fetching Asana...")
                asana_res = await tool_executor.execute_tool(
                    tool_name="asana_list_tasks",
                    arguments={
                        "limit": 20, 
                        "opt_fields": ["gid", "name", "completed", "projects.name", "memberships.section.name"]
                    },
                    user=user,
                    db=db
                )
                
                # Extract tasks
                tasks = []
                if isinstance(asana_res, list):
                    tasks = asana_res
                elif isinstance(asana_res, dict):
                    if "data" in asana_res and isinstance(asana_res["data"], list):
                         tasks = asana_res["data"]
                    elif "data" in asana_res and isinstance(asana_res["data"], dict) and "data" in asana_res["data"]:
                         tasks = asana_res["data"]["data"]
                    elif "data" in asana_res and isinstance(asana_res["data"], dict) and "items" in asana_res["data"]: # generic fallback
                         tasks = asana_res["data"]["items"]

                if tasks:
                    has_real_data = True
                    context_text += f"\nACTIVE ASANA TASKS ({len(tasks)}):\n"
                    for t in tasks[:5]:
                        if not t.get("completed"):
                            name = t.get("name", "Task")
                            # Try to find status from section
                            status = "To Do"
                            memberships = t.get("memberships", [])
                            if isinstance(memberships, list):
                                for m in memberships:
                                    section_name = m.get("section", {}).get("name", "").lower()
                                    if "progress" in section_name or "doing" in section_name:
                                        status = "In Progress"
                                        break
                                    elif "review" in section_name:
                                        status = "Review"
                                        break
                            
                            context_text += f"- [Asana] [{status}] {name}\n"
            except Exception as e:
                logging.error(f"[{datetime.now().isoformat()}] Asana Error: {e}")

        # --- Emails (Gmail) ---
        if "google_workspace" in active_platforms:
            try:
                logging.info(f"[{datetime.now().isoformat()}] Fetching Unread Emails...")
                
                email_res = await tool_executor.execute_tool(
                    tool_name="google_workspace_gmail", 
                    arguments={"operation": "read_emails", "max_results": 5},
                    user=user,
                    db=db
                )
                
                logging.info(f"[{datetime.now().isoformat()}] Gmail Result Keys: {email_res.keys() if isinstance(email_res, dict) else type(email_res)}")

                # Handle error responses
                if email_res.get("success") is False:
                    logging.error(f"Gmail fetch failed: {email_res.get('error')}")
                
                # Gmail response has 'emails' directly at top level (not nested in 'result')
                emails = email_res.get("emails", [])
                
                # Fallback: try 'result' if 'emails' is empty (for different response structures)
                if not emails:
                    if email_res.get("success") is False:
                        logging.error(f"Gmail Tool Failed: {email_res.get('error')}")
                        context_text += f"\n[System Error] Could not fetch emails: {email_res.get('error')}\n"

                    result_data = email_res.get("result", {})
                    if isinstance(result_data, dict):
                        emails = result_data.get("emails", []) or result_data.get("messages", [])
                    elif isinstance(result_data, list):
                        emails = result_data

                logging.info(f"[{datetime.now().isoformat()}] Gmail Emails Found: {len(emails) if isinstance(emails, list) else 0}")

                if emails and isinstance(emails, list):
                    has_real_data = True
                    context_text += f"\nURGENT EMAILS ({len(emails)}):\n"
                    for e in emails:
                        subject = e.get("subject", "No Subject")
                        sender = e.get("from", "Unknown")
                        snippet = e.get("snippet", "")
                        context_text += f"- From {sender}: {subject} ({snippet[:50]}...)\n"
            except Exception as e:
                logging.error(f"[{datetime.now().isoformat()}] Gmail Error: {e}")

        # --- Calendar (Google) ---
        if "google_workspace" in active_platforms:
            try:
                logging.info(f"[{datetime.now().isoformat()}] Fetching Calendar Events (from start of day)...")
                # Fetch events starting from the beginning of the current day (UTC) to provide full context
                start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                time_min_iso = start_of_day.isoformat() + "Z"
                
                calendar_res = await tool_executor.execute_tool(
                    tool_name="google_workspace_calendar", 
                    arguments={
                        "operation": "list_events", 
                        "max_results": 20, # Increased to capture full day
                        "time_min": time_min_iso
                        # tool_executor ignores order_by/single_events, so relying on defaults (or updating tool_executor separately)
                    },
                    user=user,
                    db=db
                )
                
                if calendar_res.get("success") is False:
                     error_msg = calendar_res.get("error", "Unknown error")
                     logging.error(f"Calendar Tool Failed: {error_msg}")
                     context_text += f"\n[System Error] Could not fetch calendar: {error_msg}\n"

                # Robust extraction
                events = calendar_res.get("events", [])
                if not events:
                     result_data = calendar_res.get("result", {})
                     if isinstance(result_data, dict):
                         events = result_data.get("events", []) or result_data.get("items", [])
                     elif isinstance(result_data, list):
                         events = result_data

                # Manual override: filter events that ended before now (just in case)
                # and sort by start time
                now_iso = datetime.utcnow().isoformat() + "Z"
                upcoming_events = []
                for e in events:
                    start_str = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
                    if start_str and start_str >= now_iso[:10]: # Simple string compare for ISO dates works well enough
                        upcoming_events.append(e)
                
                # Limit to 5
                events = upcoming_events[:5]

                logging.info(f"[{datetime.now().isoformat()}] Calendar Events Found: {len(events)}")
                
                if events:
                    has_real_data = True
                    cal_text = f"\nCALENDAR EVENTS ({len(events)}):\n"
                    for e in events:
                        summary = e.get("summary", "No Title")
                        start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "Unknown"))
                        cal_text += f"- [Event] {summary} at {start}\n"
                    
                    logging.info(f"Generated Calendar Context: {cal_text}")
                    context_text += cal_text
            except Exception as e:
                logging.error(f"[{datetime.now().isoformat()}] Calendar Error: {e}")
        
        logging.info(f"Final Context Text Length: {len(context_text)}")
        if len(context_text) > 0:
            logging.info(f"Context Sample: {context_text[:100]}...")

    except Exception as e:
        logging.error(f"Error fetching data for briefing: {e}")
        # Continue to fallback if fetching fails

        # 2. If no data, return Mock Data (Fallback)
    if not has_real_data:
        logging.info("No real data found or connections missing. Using fallback mock data.")
        return {
            "greeting": f"{greeting_prefix}, {user.name.split(' ')[0] if hasattr(user, 'name') else 'Creator'}",
            "headline": "Ready to connect your world?",
            "summary": "I couldn't find any connected calendars or task apps yet. Connect Google Workspace or Jira in Settings to see your real daily briefing here.",
            "time_context": time_context,
            "priorities": [
                "Connect Google Workspace in Settings",
                "Connect Jira or ClickUp", 
                "Explore the Marketplace"
            ],
            "risks": [],
            "suggested_actions": [
                {"label": "Go to Settings", "action": "nav-settings"},
                {"label": "View Marketplace", "action": "nav-marketplace"}
            ],
            "calendar_events": [],
            "conversations": [],
            "weekly_pulse": {
                "score": 85,
                "trend": "up",
                "completedTasks": 12,
                "focusHours": 5,
                "meetingHours": 3
            }
        }

    # 3. Generate Briefing with LLM
    try:
        logging.info(f"Generating briefing with context found from: {active_platforms}")
        system_prompt = f"""
        You are an elite executive assistant. 
        Analyze the user's calendar, tasks, and emails for today.
        The current time of day is: {time_context}
        
        IMPORTANT:
        1. If CALENDAR EVENTS are present, you MUST mention the schedule in the 'summary' and list the first event in 'priorities'.
        2. Use the source name in the priorities list e.g. '[Jira] Fix bug', '[Trello] Review card', '[Calendar] Meeting'.
        3. Identify risks like overlapping meetings or tight turnarounds using the calendar times.
        4. Translate any non-English text (e.g. event titles, email subjects) into English for the summary and priorities.
        5. Use '{greeting_prefix}' as the greeting prefix (not always 'Good morning').
        
        Ensure you include items from ALL connected sources if available (Jira, ClickUp, Trello, Asana, Calendar, Email).
        
        Return a valid JSON object (NO markdown formatting, just raw JSON) with this structure:
        {{
            "greeting": "{greeting_prefix}",
            "headline": "3-5 word motivating headline based on workload",
            "summary": "2-3 sentence summary in ENGLISH of the day's key items, SPECIFICALLY mentioning the schedule if one exists.",
            "time_context": "{time_context}",
            "priorities": ["List of 3-5 top priorities in ENGLISH, prefixed with Source e.g. [ClickUp] Task Name"],
            "urgent_emails": [{{"sender": "Name", "subject": "Subject (English)", "reason": "Why it's urgent (English)"}}],
            "risks": ["List of potential conflicts or risks in ENGLISH"],
            "suggested_actions": [
                {{"label": "Draft Replies", "action": "email.draft_replies"}},
                {{"label": "Block Focus Time", "action": "calendar.schedule_focus"}},
                {{"label": "Go to Calendar", "action": "nav-calendar"}},
                {{"label": "Review Tasks", "action": "nav-tasks"}}
            ]
        }}
        """
        
        user_prompt = f"User: {user.name}\nDate: {datetime.now().strftime('%A, %B %d')}\n\nDATA:\n{context_text}"
        
        response = await llm_service.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=800,
            use_background_model=True
        )
        
        # Parse JSON
        content = response.content
        # Strip code blocks if present
        if "```json" in content:
            content = content.replace("```json", "").replace("```", "")
        elif "```" in content:
             content = content.replace("```", "")
             
        data = json.loads(content.strip())
        
        # INJECT STRUCTURED DATA (Phase 2 Enhancement)
        # We manually inject the robustly parsed data to ensure the frontend gets clean structures
        # even if the LLM hallucinated or didn't include them.
        data["calendar_events"] = raw_calendar_events
        
        # Mock/Placeholder Data for Conversations (until we have a real tool for this)
        data["conversations"] = [
            {"id": "c1", "platform": "Slack", "sender": "Sarah Connor", "preview": "Can we sync on the SkyNet project?", "time": "10:30 AM", "unread": True},
            {"id": "c2", "platform": "Teams", "sender": "Darth Vader", "preview": "I find your lack of faith disturbing.", "time": "9:15 AM", "unread": True},
            {"id": "c3", "platform": "Slack", "sender": "Prod Check", "preview": "Deployment successful 🚀", "time": "8:00 AM", "unread": False}
        ]
        
        # Mock/Calculated Data for Weekly Pulse
        # In Phase 5, this will be real analytics
        data["weekly_pulse"] = {
            "score": 92,
            "trend": "up", # 'up', 'down', 'neutral'
            "completedTasks": 24, # Could calculate this from Jira if we wanted
            "focusHours": 12,
            "meetingHours": 8
        }
        
        return data

    except Exception as e:
        logging.error(f"LLM Generation failed: {e}")
        # Fallback if LLM fails
        return {
             "greeting": f"{greeting_prefix}, {user.name.split(' ')[0]}",
             "headline": "Here is your data",
             "summary": "I found some data but couldn't generate the full AI summary right now.",
             "time_context": time_context,
             "priorities": ["Check Calendar", "Review Tasks"],
             "risks": [],
             "suggested_actions": [],
             "calendar_events": raw_calendar_events, # Return what we found at least
             "conversations": [], 
             "weekly_pulse": {"score": 0, "trend": "neutral", "completedTasks": 0, "focusHours": 0, "meetingHours": 0}
        }


@router.post("/action")
async def execute_briefing_action(
    payload: Dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    action_id = payload.get("action")
    logging.info(f"Executing briefing action: {action_id}")
    
    if action_id == "email.draft_replies":
        # 1. Fetch urgent emails (re-fetch for freshness)
        email_res = await tool_executor.execute_tool(
            tool_name="google_workspace_gmail", 
            arguments={"operation": "read_emails", "max_results": 3},
            user=user,
            db=db
        )
        
        # Robust extraction matching the morning briefing logic
        emails = email_res.get("emails", [])
        if not emails:
            result_data = email_res.get("result", {})
            if isinstance(result_data, dict):
                emails = result_data.get("emails", []) or result_data.get("messages", [])
            elif isinstance(result_data, list):
                emails = result_data
        
        results = []
        if emails and isinstance(emails, list):
            for email in emails:
                # 2. Generate Reply with LLM
                prompt = f"Draft a professional, concise reply to this email:\n\nSubject: {email.get('subject')}\nSnippet: {email.get('snippet')}\n\nReply:"
                reply_res = await llm_service.chat_completion([{"role": "user", "content": prompt}], max_tokens=300, use_background_model=True)
                reply_body = reply_res.content
                
                # 3. Create Draft
                draft_res = await tool_executor.execute_tool(
                    tool_name="google_workspace_gmail",
                    arguments={
                        "operation": "create_draft", 
                        "to": email.get("from"),
                        "subject": "Re: " + email.get("subject", ""),
                        "body": reply_body
                    },
                    user=user,
                    db=db
                )
                
                if isinstance(draft_res, dict) and (draft_res.get("success") is False or "error" in draft_res):
                     error_msg = draft_res.get("error", "Unknown error")
                     results.append(f"Failed to create draft for {email.get('subject')}: {error_msg}")
                else:
                     results.append(f"Draft created for {email.get('subject')}")
            
        return {"success": True, "message": f"Created {len(results)} drafts", "details": results}

    elif action_id == "calendar.schedule_focus":
        # Schedule 2 hours of focus time starting next hour
        now = datetime.utcnow()
        # Handle simple next hour logic
        start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end_time = start_time + timedelta(hours=2)
        
        start_iso = start_time.isoformat() + "Z"
        end_iso = end_time.isoformat() + "Z"
        
        event_res = await tool_executor.execute_tool(
            tool_name="google_workspace_calendar",
            arguments={
                "operation": "create_event",
                "summary": "Deep Work 🧠",
                "description": "Focus time scheduled by AI Morning Briefing.",
                "start_time": start_iso,
                "end_time": end_iso
            },
            user=user,
            db=db
        )
        return {"success": True, "message": "Focus time scheduled for 2 hours.", "details": event_res}

    return {"success": False, "message": "Unknown action"}


class AskAIRequest(BaseModel):
    question: str
    context: Optional[str] = None  # Optional context from the current briefing


class AskAIResponse(BaseModel):
    answer: str
    suggestions: Optional[List[str]] = None


@router.post("/ask", response_model=AskAIResponse)
async def ask_ai_followup(
    request: AskAIRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle follow-up questions from the briefing modal.
    Uses LLM to provide contextual responses based on the user's question.
    Dynamically fetches relevant data (emails, calendar, tasks) based on question type.
    """
    logging.info(f"User {user.id} asking AI: {request.question}")
    question_lower = request.question.lower()
    
    try:
        # Build dynamic context based on question type
        data_context = []
        
        # Fetch emails if question is about emails/inbox
        if any(word in question_lower for word in ["email", "inbox", "mail", "reply", "urgent", "message", "unread"]):
            try:
                email_res = await tool_executor.execute_tool(
                    tool_name="google_workspace_gmail",
                    arguments={"operation": "read_emails", "max_results": 10},
                    user=user,
                    db=db
                )
                emails = email_res.get("emails", [])
                if not emails:
                    result_data = email_res.get("result", {})
                    if isinstance(result_data, dict):
                        emails = result_data.get("emails", []) or result_data.get("messages", [])
                    elif isinstance(result_data, list):
                        emails = result_data
                
                if emails:
                    email_summary = "\n\nYour recent emails:\n"
                    for i, email in enumerate(emails[:10], 1):
                        sender = email.get('from', 'Unknown')
                        subject = email.get('subject', 'No subject')
                        snippet = email.get('snippet', '')[:100]
                        is_unread = email.get('unread', False)
                        status = "[UNREAD]" if is_unread else ""
                        email_summary += f"{i}. {status} From: {sender}\n   Subject: {subject}\n   Preview: {snippet}...\n\n"
                    data_context.append(email_summary)
            except Exception as e:
                logging.warning(f"Failed to fetch emails for Ask AI: {e}")
        
        # Fetch calendar if question is about meetings/schedule
        if any(word in question_lower for word in ["calendar", "meeting", "schedule", "event", "today", "appointment", "free", "busy"]):
            try:
                now = datetime.utcnow()
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_day = start_of_day + timedelta(days=1)
                
                calendar_res = await tool_executor.execute_tool(
                    tool_name="google_workspace_calendar",
                    arguments={
                        "operation": "list_events",
                        "time_min": start_of_day.isoformat() + "Z",
                        "time_max": end_of_day.isoformat() + "Z",
                        "max_results": 15
                    },
                    user=user,
                    db=db
                )
                events = calendar_res.get("events", [])
                if not events:
                    result_data = calendar_res.get("result", {})
                    if isinstance(result_data, dict):
                        events = result_data.get("events", []) or result_data.get("items", [])
                    elif isinstance(result_data, list):
                        events = result_data
                
                if events:
                    cal_summary = "\n\nYour calendar today:\n"
                    for event in events[:15]:
                        title = event.get('summary', 'Untitled')
                        start = event.get('start', {})
                        start_time = start.get('dateTime', start.get('date', 'All day'))
                        if 'T' in str(start_time):
                            try:
                                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                                start_time = dt.strftime('%I:%M %p')
                            except:
                                pass
                        cal_summary += f"- {start_time}: {title}\n"
                    data_context.append(cal_summary)
            except Exception as e:
                logging.warning(f"Failed to fetch calendar for Ask AI: {e}")
        
        # Build the final context
        full_context = request.context or ""
        if data_context:
            full_context += "\n".join(data_context)
        
        system_prompt = """You are an intelligent productivity assistant helping a user manage their day.
You have access to their REAL calendar, tasks, and emails data which is provided below.
Analyze the actual data carefully and provide specific, actionable responses.
Reference specific emails by sender/subject when discussing emails.
Reference specific meetings by name/time when discussing calendar.
Keep responses concise but informative (2-4 sentences).
Be friendly and professional."""

        user_prompt = f"""User: {user.name}
Question: {request.question}

{full_context if full_context else 'No additional context available.'}

Based on the ACTUAL data provided above, answer the user's question specifically and accurately:"""

        response = await llm_service.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        
        answer = response.content.strip()
        
        # Generate follow-up suggestions based on the question
        suggestions = []
        if "meeting" in question_lower or "calendar" in question_lower:
            suggestions = ["Show my full calendar", "Schedule focus time", "Find a meeting time"]
        elif "email" in question_lower or "inbox" in question_lower:
            suggestions = ["Draft replies to urgent emails", "Show unread emails", "Archive old emails"]
        elif "task" in question_lower or "priority" in question_lower:
            suggestions = ["Show all my tasks", "What's most urgent?", "Mark tasks complete"]
        else:
            suggestions = ["What should I focus on?", "Schedule a break", "Review my day"]
        
        return AskAIResponse(answer=answer, suggestions=suggestions)
        
    except Exception as e:
        logging.error(f"Ask AI failed: {e}")
        return AskAIResponse(
            answer="I'm having trouble processing your question right now. Please try again.",
            suggestions=["What's on my calendar?", "Show my priorities"]
        )


# =============================================================================
# Phase 3: Intelligent Inbox++ - Message Analysis
# =============================================================================

class MessageToAnalyze(BaseModel):
    id: str
    source: str  # gmail, slack, teams, outlook
    sender: str
    subject: str
    preview: str
    full_content: Optional[str] = None

class AnalyzeMessagesRequest(BaseModel):
    messages: List[MessageToAnalyze]

class EnrichedMessage(BaseModel):
    id: str
    priority: int  # 1-5 (5 = most urgent)
    labels: List[str]  # ["Action Required", "FYI", "Marketing", "Personal", "Waiting"]
    summary: Optional[str] = None  # 1-line AI summary
    quick_replies: Optional[List[str]] = None  # Up to 3 suggested brief replies

class AnalyzeMessagesResponse(BaseModel):
    success: bool
    enriched: Dict[str, EnrichedMessage]  # message_id -> enrichment

@router.post("/analyze-messages", response_model=AnalyzeMessagesResponse)
async def analyze_messages(
    request: AnalyzeMessagesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    AI-powered message analysis for Intelligent Inbox++.
    Analyzes messages and returns priority scores, labels, summaries, and quick reply suggestions.
    """
    try:
        if not request.messages:
            return AnalyzeMessagesResponse(success=True, enriched={})
        
        # Build prompt for batch analysis
        messages_text = ""
        for i, msg in enumerate(request.messages[:20], 1):  # Limit to 20 messages
            content = msg.full_content or msg.preview
            messages_text += f"""
MESSAGE {i}:
- ID: {msg.id}
- Source: {msg.source}
- From: {msg.sender}
- Subject: {msg.subject}
- Content: {content[:500]}...
---
"""
        
        system_prompt = """You are an AI assistant analyzing inbox messages for a productivity app.
For each message, provide:
1. Priority (1-5): 1=Info/Newsletter, 2=Low, 3=Medium, 4=High, 5=Critical/Urgent
2. Labels: Choose from ["Action Required", "Waiting", "FYI", "Marketing", "Personal", "Financial", "Meeting", "Newsletter"]
3. Summary: One concise sentence summarizing the message
4. Quick Replies: 2-3 brief professional response options (each under 20 words)

Respond in valid JSON format like this:
{
  "analyses": [
    {
      "id": "message_id_here",
      "priority": 4,
      "labels": ["Action Required", "Meeting"],
      "summary": "Client requesting urgent meeting to discuss Q1 results",
      "quick_replies": ["I'll check my calendar and get back to you.", "How about tomorrow at 2 PM?", "Can we discuss via email first?"]
    }
  ]
}

Be accurate and helpful. Prioritize based on urgency keywords, sender importance, and deadlines."""

        user_prompt = f"""Analyze these {len(request.messages)} messages for user {user.name}:

{messages_text}

Return JSON with analyses for each message ID."""

        response = await llm_service.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3  # Lower for more consistent output
        )
        
        # Parse LLM response
        content = response.content.strip()
        
        # Extract JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            content = json_match.group()
        
        try:
            parsed = json.loads(content)
            analyses = parsed.get("analyses", [])
        except json.JSONDecodeError:
            logging.warning(f"Failed to parse LLM response as JSON: {content[:200]}")
            analyses = []
        
        # Build enriched dictionary
        enriched: Dict[str, EnrichedMessage] = {}
        for analysis in analyses:
            msg_id = analysis.get("id", "")
            if msg_id:
                enriched[msg_id] = EnrichedMessage(
                    id=msg_id,
                    priority=min(5, max(1, analysis.get("priority", 3))),
                    labels=analysis.get("labels", ["FYI"])[:3],  # Max 3 labels
                    summary=analysis.get("summary"),
                    quick_replies=analysis.get("quick_replies", [])[:3]  # Max 3 replies
                )
        
        # Fill in any missing messages with defaults
        for msg in request.messages:
            if msg.id not in enriched:
                # Heuristic-based fallback
                priority = 3
                labels = ["FYI"]
                
                text_lower = (msg.subject + " " + msg.preview).lower()
                if any(word in text_lower for word in ["urgent", "asap", "critical", "deadline", "immediately"]):
                    priority = 5
                    labels = ["Action Required"]
                elif any(word in text_lower for word in ["please review", "approval", "request", "action"]):
                    priority = 4
                    labels = ["Action Required"]
                elif any(word in text_lower for word in ["newsletter", "unsubscribe", "promotion"]):
                    priority = 1
                    labels = ["Newsletter", "Marketing"]
                elif any(word in text_lower for word in ["meeting", "calendar", "invite", "schedule"]):
                    priority = 3
                    labels = ["Meeting"]
                
                enriched[msg.id] = EnrichedMessage(
                    id=msg.id,
                    priority=priority,
                    labels=labels,
                    summary=None,
                    quick_replies=None
                )
        
        logging.info(f"Analyzed {len(enriched)} messages for user {user.id}")
        return AnalyzeMessagesResponse(success=True, enriched=enriched)
        
    except Exception as e:
        logging.error(f"Message analysis failed: {e}")
        # Return empty enrichment on error - frontend will use defaults
        return AnalyzeMessagesResponse(success=False, enriched={})


# ===============================================
# Phase 4: Intelligent Scheduling Engine
# ===============================================

from ..services.scheduling_service import scheduling_service, TimeSlot, Conflict

class ScheduleRequest(BaseModel):
    """Natural language scheduling request."""
    query: str  # e.g., "Schedule 1 hour meeting with John tomorrow at 2pm"
    duration_minutes: Optional[int] = None
    preferences: Optional[Dict[str, Any]] = None


class ScheduleResponse(BaseModel):
    success: bool
    event: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[Dict[str, Any]]] = None
    message: str


class FindSlotsRequest(BaseModel):
    duration_minutes: int = 30
    date_range_days: int = 7
    prefer_morning: bool = False
    prefer_afternoon: bool = False
    avoid_back_to_back: bool = True


class FindSlotsResponse(BaseModel):
    success: bool
    slots: List[Dict[str, Any]]


class ProtectFocusRequest(BaseModel):
    hours_per_week: int = 10


class ProtectFocusResponse(BaseModel):
    success: bool
    focus_blocks: List[Dict[str, Any]]
    message: str


class BufferTimeRequest(BaseModel):
    buffer_minutes: int = 15


class BufferTimeResponse(BaseModel):
    success: bool
    buffer_suggestions: List[Dict[str, Any]]
    message: str


class DetectConflictsRequest(BaseModel):
    start: str  # ISO format
    end: str    # ISO format


class DetectConflictsResponse(BaseModel):
    success: bool
    conflicts: List[Dict[str, Any]]
    has_conflicts: bool


@router.post("/schedule", response_model=ScheduleResponse)
async def schedule_with_ai(
    request: ScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Natural language scheduling. Parse user intent and create calendar event.
    Example: "Schedule 1 hour meeting tomorrow at 2pm"
    """
    logging.info(f"AI Schedule request from user {user.id}: {request.query}")
    
    try:
        # Get calendar events for context
        calendar_events = []
        try:
            result = await tool_executor.execute_tool(
                tool_name="google_workspace_calendar",
                arguments={"operation": "list_events", "max_results": 50},
                user=user,
                db=db
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        # Use LLM to parse the scheduling intent
        parse_prompt = f"""Parse this scheduling request and extract:
1. Event title (infer if not specified)
2. Duration in minutes (default 30)
3. Preferred date/time (relative to today: {datetime.now().strftime('%Y-%m-%d %H:%M')})
4. Attendees (if mentioned)

Request: "{request.query}"

Respond ONLY with valid JSON:
{{
    "title": "string",
    "duration_minutes": number,
    "preferred_date": "YYYY-MM-DD",
    "preferred_time": "HH:MM" or null,
    "attendees": ["email1", "email2"] or []
}}"""
        
        llm_response = await llm_service.chat_completion(
            messages=[{"role": "user", "content": parse_prompt}],
            max_tokens=200
        )
        llm_text = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
        
        # Parse LLM response
        try:
            # Extract JSON from response
            json_start = llm_text.find('{')
            json_end = llm_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(llm_text[json_start:json_end])
            else:
                raise ValueError("No JSON found in response")
        except:
            # Default parsing if LLM fails
            parsed = {
                "title": "Meeting",
                "duration_minutes": request.duration_minutes or 30,
                "preferred_date": (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                "preferred_time": None,
                "attendees": []
            }
        
        duration = parsed.get("duration_minutes", 30)
        
        # If specific time given, try to create event directly
        if parsed.get("preferred_time"):
            try:
                event_date = datetime.strptime(parsed["preferred_date"], '%Y-%m-%d')
                time_parts = parsed["preferred_time"].split(":")
                start_dt = event_date.replace(hour=int(time_parts[0]), minute=int(time_parts[1]))
                end_dt = start_dt + timedelta(minutes=duration)
                
                # Check for conflicts
                conflicts = await scheduling_service.detect_conflicts(
                    user.id, start_dt, end_dt, calendar_events
                )
                
                if conflicts:
                    # Find alternative slots
                    slots = await scheduling_service.find_optimal_slots(
                        user.id, duration, 7, 
                        request.preferences or {},
                        calendar_events
                    )
                    return ScheduleResponse(
                        success=False,
                        event=None,
                        suggestions=[{
                            "start": s.start.isoformat(),
                            "end": s.end.isoformat(),
                            "score": s.score,
                            "reason": s.reason
                        } for s in slots[:5]],
                        message=f"Conflict detected with '{conflicts[0].event_title}'. Here are some alternatives."
                    )
                
                # Create the event
                event_result = await tool_executor.execute(
                    user_id=user.id,
                    db=db,
                    platform="google_workspace_calendar",
                    params={
                        "operation": "create_event",
                        "summary": parsed.get("title", "Meeting"),
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "attendees": parsed.get("attendees", [])
                    }
                )
                
                if event_result.get("success"):
                    return ScheduleResponse(
                        success=True,
                        event=event_result.get("result", {}).get("event"),
                        suggestions=None,
                        message=f"✅ Scheduled '{parsed.get('title')}' for {start_dt.strftime('%B %d at %I:%M %p')}"
                    )
            except Exception as e:
                logging.warning(f"Direct scheduling failed: {e}")
        
        # Find optimal slots if no specific time or creation failed
        slots = await scheduling_service.find_optimal_slots(
            user.id, duration, 7,
            request.preferences or {},
            calendar_events
        )
        
        return ScheduleResponse(
            success=True,
            event=None,
            suggestions=[{
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
                "score": s.score,
                "reason": s.reason
            } for s in slots[:5]],
            message=f"Found {len(slots)} available slots for your {duration}-minute {parsed.get('title', 'event')}."
        )
        
    except Exception as e:
        logging.error(f"AI scheduling failed: {e}")
        return ScheduleResponse(
            success=False,
            event=None,
            suggestions=None,
            message=f"Scheduling failed: {str(e)}"
        )


@router.post("/find-slots", response_model=FindSlotsResponse)
async def find_available_slots(
    request: FindSlotsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Find available time slots based on calendar and preferences."""
    logging.info(f"Finding slots for user {user.id}: {request.duration_minutes}min")
    
    try:
        # Fetch calendar events
        calendar_events = []
        try:
            result = await tool_executor.execute(
                user_id=user.id,
                db=db,
                platform="google_workspace_calendar",
                params={"operation": "list_events", "max_results": 100}
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        preferences = {
            "prefer_morning": request.prefer_morning,
            "prefer_afternoon": request.prefer_afternoon,
            "avoid_back_to_back": request.avoid_back_to_back
        }
        
        slots = await scheduling_service.find_optimal_slots(
            user.id,
            request.duration_minutes,
            request.date_range_days,
            preferences,
            calendar_events
        )
        
        return FindSlotsResponse(
            success=True,
            slots=[{
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
                "score": s.score,
                "reason": s.reason
            } for s in slots]
        )
        
    except Exception as e:
        logging.error(f"Find slots failed: {e}")
        return FindSlotsResponse(success=False, slots=[])


@router.post("/protect-focus", response_model=ProtectFocusResponse)
async def protect_focus_time(
    request: ProtectFocusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate focus time blocks to protect deep work."""
    logging.info(f"Protecting focus time for user {user.id}: {request.hours_per_week}h/week")
    
    try:
        # Fetch calendar events
        calendar_events = []
        try:
            result = await tool_executor.execute(
                user_id=user.id,
                db=db,
                platform="google_workspace_calendar",
                params={"operation": "list_events", "max_results": 100}
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        focus_blocks = await scheduling_service.protect_focus_time(
            user.id,
            request.hours_per_week,
            calendar_events
        )
        
        total_hours = sum(b["duration_hours"] for b in focus_blocks)
        
        return ProtectFocusResponse(
            success=True,
            focus_blocks=focus_blocks,
            message=f"Found {len(focus_blocks)} available focus blocks totaling {total_hours:.1f} hours. Click to create them on your calendar."
        )
        
    except Exception as e:
        logging.error(f"Focus time protection failed: {e}")
        return ProtectFocusResponse(
            success=False,
            focus_blocks=[],
            message=f"Failed: {str(e)}"
        )


@router.post("/add-buffers", response_model=BufferTimeResponse)
async def add_buffer_time(
    request: BufferTimeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Identify where buffer time should be added between meetings."""
    logging.info(f"Analyzing buffer time for user {user.id}")
    
    try:
        # Fetch calendar events
        calendar_events = []
        try:
            result = await tool_executor.execute(
                user_id=user.id,
                db=db,
                platform="google_workspace_calendar",
                params={"operation": "list_events", "max_results": 100}
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        buffer_suggestions = await scheduling_service.add_buffer_time(
            user.id,
            request.buffer_minutes,
            calendar_events
        )
        
        return BufferTimeResponse(
            success=True,
            buffer_suggestions=buffer_suggestions,
            message=f"Found {len(buffer_suggestions)} back-to-back meetings that could use {request.buffer_minutes}min buffers."
        )
        
    except Exception as e:
        logging.error(f"Buffer time analysis failed: {e}")
        return BufferTimeResponse(
            success=False,
            buffer_suggestions=[],
            message=f"Failed: {str(e)}"
        )


@router.post("/detect-conflicts", response_model=DetectConflictsResponse)
async def detect_scheduling_conflicts(
    request: DetectConflictsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check for conflicts with a proposed time slot."""
    logging.info(f"Detecting conflicts for user {user.id}")
    
    try:
        proposed_start = datetime.fromisoformat(request.start.replace('Z', '+00:00')).replace(tzinfo=None)
        proposed_end = datetime.fromisoformat(request.end.replace('Z', '+00:00')).replace(tzinfo=None)
        
        # Fetch calendar events
        calendar_events = []
        try:
            result = await tool_executor.execute(
                user_id=user.id,
                db=db,
                platform="google_workspace_calendar",
                params={"operation": "list_events", "max_results": 100}
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        conflicts = await scheduling_service.detect_conflicts(
            user.id,
            proposed_start,
            proposed_end,
            calendar_events
        )
        
        return DetectConflictsResponse(
            success=True,
            conflicts=[{
                "event_id": c.event_id,
                "event_title": c.event_title,
                "start": c.start.isoformat(),
                "end": c.end.isoformat(),
                "overlap_minutes": c.overlap_minutes
            } for c in conflicts],
            has_conflicts=len(conflicts) > 0
        )
        
    except Exception as e:
        logging.error(f"Conflict detection failed: {e}")
        return DetectConflictsResponse(
            success=False,
            conflicts=[],
            has_conflicts=False
        )


# =============================================================================
# Phase 5: AI Reply Feature (Business+ Feature)
# =============================================================================

class AIReplyRequest(BaseModel):
    """Request model for AI-powered reply generation."""
    original_message: str
    context: Optional[str] = None
    tone: str = "professional"  # professional, friendly, concise, formal

class AIReplyResponse(BaseModel):
    """Response model for AI-generated reply."""
    success: bool
    reply: Optional[str] = None
    error: Optional[str] = None
    tone_used: str = "professional"

@router.post("/generate-reply", response_model=AIReplyResponse)
async def generate_ai_reply(
    request: AIReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate AI-powered email/message reply (Business+ feature).
    
    This endpoint is gated to Business tier and above.
    Uses LLM to generate contextual, professional replies.
    """
    from ..services.feature_flags import FeatureGate
    
    # Check feature access (Business+ only)
    if not FeatureGate.has_feature(user, "inbox_ai_reply"):
        return AIReplyResponse(
            success=False,
            error="Upgrade to Business or higher for AI-powered replies",
            tone_used=request.tone
        )
    
    try:
        # Define tone instructions
        tone_instructions = {
            "professional": "Write in a professional, business-appropriate tone. Be courteous and clear.",
            "friendly": "Write in a warm, friendly tone while remaining professional. Use a conversational style.",
            "concise": "Write a brief, to-the-point reply. Focus on key information only.",
            "formal": "Write in a formal, official tone. Use proper business language and structure."
        }
        
        tone_guide = tone_instructions.get(request.tone, tone_instructions["professional"])
        
        # Build the prompt
        prompt = f"""Generate a reply to the following message. {tone_guide}

ORIGINAL MESSAGE:
{request.original_message}

{f"ADDITIONAL CONTEXT: {request.context}" if request.context else ""}

INSTRUCTIONS:
- Write only the reply text, no subject line or greetings like "Dear..." unless appropriate
- Match the original message's language if not English
- Be helpful and address the sender's needs
- Keep the response appropriately sized (short for simple queries, detailed for complex ones)

REPLY:"""

        # Generate reply using LLM service
        reply = await llm_service.generate_text(prompt, max_tokens=500)
        
        # Clean up the reply (remove any "REPLY:" prefix if present)
        if reply.startswith("REPLY:"):
            reply = reply[6:].strip()
        
        return AIReplyResponse(
            success=True,
            reply=reply.strip(),
            tone_used=request.tone
        )
        
    except Exception as e:
        logging.error(f"AI Reply generation failed: {e}")
        return AIReplyResponse(
            success=False,
            error=f"Failed to generate reply: {str(e)}",
            tone_used=request.tone
        )

