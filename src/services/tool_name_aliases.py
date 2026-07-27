"""
Map Ask AI registry tool names ↔ executor dispatch names.

Product rule: the name exposed by DynamicToolRegistry must execute.
Aliases keep PrecisionToolRouter / legacy executor names working.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# registry_or_router_name -> (executor_tool_name, default_operation_or_None)
TOOL_NAME_ALIASES: Dict[str, Tuple[str, Optional[str]]] = {
    # Outlook
    "outlook_read_emails": ("outlook_email_management", "read_emails"),
    "outlook_send_email": ("outlook_email_management", "send_email"),
    "outlook_search_emails": ("outlook_email_management", "search_emails"),
    "outlook_email_management": ("outlook_email_management", None),
    # Notion
    "notion_search_pages": ("notion_workspace_management", "search_pages"),
    "notion_create_page": ("notion_workspace_management", "create_page"),
    "notion_workspace_management": ("notion_workspace_management", None),
    "notion_workspace": ("notion_workspace_management", None),
    # Trello
    "trello_get_boards": ("trello_project_management", "get_boards"),
    "trello_search_cards": ("trello_project_management", "search_cards"),
    "trello_create_card": ("trello_project_management", "create_card"),
    "trello_project_management": ("trello_project_management", None),
    "trello_board_management": ("trello_project_management", None),
    # Jira
    "jira_get_projects": ("jira_issue_tracking", "get_projects"),
    "jira_search_issues": ("jira_issue_tracking", "search_issues"),
    "jira_create_issue": ("jira_issue_tracking", "create_issue"),
    "jira_issue_tracking": ("jira_issue_tracking", None),
    "jira_project_management": ("jira_issue_tracking", None),
    # Power BI
    "powerbi_list_workspaces": ("powerbi_workspace_management", "list"),
    "powerbi_list_datasets": ("powerbi_dataset_operations", "list"),
    "powerbi_list_reports": ("powerbi_report_operations", "list"),
    "powerbi_list_dashboards": ("powerbi_dashboard_operations", "list"),
    "powerbi_execute_dax_query": ("powerbi_dataset_operations", "execute_query"),
    "powerbi_refresh_dataset": ("powerbi_dataset_operations", "refresh"),
    "powerbi_get_embed_token": ("powerbi_report_operations", "get_embed_token"),
    "powerbi_get_analytics_summary": ("powerbi_report_operations", "get_analytics"),
    "powerbi_workspace_management": ("powerbi_workspace_management", None),
    "powerbi_dataset_operations": ("powerbi_dataset_operations", None),
    "powerbi_report_operations": ("powerbi_report_operations", None),
    "powerbi_dashboard_operations": ("powerbi_dashboard_operations", None),
    # Xero
    "xero_accounting": ("xero_accounting", None),
    "xero_get_company_info": ("xero_accounting", "get_company_info"),
    "xero_invoices": ("xero_accounting", "invoices"),
    "xero_reports": ("xero_accounting", "reports"),
    "xero_lists": ("xero_accounting", "lists"),
    # HubSpot / Salesforce / Airtable router ghosts
    "hubspot_crm_management": ("hubspot_contact_operations", "read"),
    "salesforce_crm_management": ("salesforce_general_operations", None),
    "airtable_operations": ("airtable_record_management", "list_records"),
    # QuickBooks
    "quickbooks_accounting": ("quickbooks_accounting", None),
}


def resolve_tool_name(tool_name: str, arguments: Optional[dict] = None) -> Tuple[str, dict]:
    """
    Return (canonical_executor_name, arguments_with_operation).
    """
    args = dict(arguments or {})
    entry = TOOL_NAME_ALIASES.get(tool_name)
    if not entry:
        return tool_name, args
    canonical, default_op = entry
    if default_op and not (args.get("operation") or args.get("action")):
        args["operation"] = default_op
    return canonical, args
