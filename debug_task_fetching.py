
import asyncio
import logging
from src.services.jira_service import JiraService
from src.services.trello_service import TrelloService
from src.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_tasks():
    print("--- Starting Debug Session ---")
    
    # 1. Test Jira
    print("\n[Jira] Testing search_issues...")
    try:
        jira = JiraService()
        await jira.initialize()
        # Query used in UnifiedCalendar.tsx: 'statusCategory in ("To Do", "In Progress") order by updated DESC'
        # But wait, looking at UnifiedCalendar.tsx line 100: 
        # jql: 'statusCategory in ("To Do", "In Progress") order by updated DESC'
        jql = 'statusCategory in ("To Do", "In Progress") order by updated DESC'
        print(f"Executing JQL: {jql}")
        jira_res = await jira.search_issues(jql=jql)
        print(f"Jira Result Success: {jira_res.get('success')}")
        if jira_res.get('success'):
            issues = jira_res.get('issues', [])
            print(f"Found {len(issues)} issues.")
            for i in issues[:3]:
                print(f" - {i['key']}: {i['summary']} (Status: {i['status']})")
        else:
            print(f"Jira Error: {jira_res.get('error')}")
    except Exception as e:
        print(f"Jira Exception: {e}")

    # 2. Test Trello
    print("\n[Trello] Testing search_cards...")
    try:
        trello = TrelloService()
        await trello.initialize()
        # Query used in UnifiedCalendar.tsx line 103: query: 'is:open'
        query = 'is:open'
        print(f"Executing Query: {query}")
        trello_res = await trello.search_cards(query=query)
        print(f"Trello Result Success: {trello_res.get('success')}")
        if trello_res.get('success'):
            cards = trello_res.get('cards', [])
            print(f"Found {len(cards)} cards.")
            for c in cards[:3]:
                print(f" - {c['name']} (List: {c.get('list', {}).get('name')})")
        else:
            print(f"Trello Error: {trello_res.get('error')}")
    except Exception as e:
        print(f"Trello Exception: {e}")

    print("\n--- End Debug Session ---")

if __name__ == "__main__":
    asyncio.run(debug_tasks())
