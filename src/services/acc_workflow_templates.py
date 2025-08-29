"""
ACC Workflow Templates

Pre-defined workflow templates for ACC ambient agents to handle
issue notifications and automated responses via various communication channels.
"""

import json
from typing import Any, Dict, List


class ACCWorkflowTemplates:
    """Templates for ACC ambient agent workflows."""
    
    @staticmethod
    def duplicate_issue_alert_workflow() -> Dict[str, Any]:
        """Workflow template for duplicate issue alerts."""
        return {
            "name": "ACC Duplicate Issue Alert",
            "description": "Automatically alert teams when potential duplicate issues are detected",
            "trigger_type": "event",
            "trigger_config": {
                "event_type": "acc_issue_duplicate_detected",
                "source": "acc_ambient_agent"
            },
            "variables": {
                "notification_channels": ["slack", "email"],
                "alert_priority": "medium",
                "auto_comment": True,
                "include_similarity_score": True
            },
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "slack_send_message",
                    "description": "Send Slack notification about duplicate issue",
                    "tool_parameters": {
                        "channel": "{{workflow.variables.slack_channel}}",
                        "message": """🚨 **Potential Duplicate Issue Detected**

**Project:** {{trigger_data.project_name}}
**New Issue:** {{trigger_data.issue.title}} (ID: {{trigger_data.issue.id}})
**Similarity Score:** {{trigger_data.similarity_score}}%

**Similar Issues:**
{{#each trigger_data.similar_issues}}
• {{this.title}} (ID: {{this.id}})
{{/each}}

**Action Required:** Please review and determine if this is a duplicate before proceeding.
**Review Link:** {{trigger_data.issue_url}}""",
                        "attachments": [
                            {
                                "color": "warning",
                                "fields": [
                                    {
                                        "title": "Confidence",
                                        "value": "{{trigger_data.confidence}}%",
                                        "short": True
                                    },
                                    {
                                        "title": "Project",
                                        "value": "{{trigger_data.project_name}}",
                                        "short": True
                                    }
                                ]
                            }
                        ]
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "notification_channels",
                        "operator": "contains",
                        "value": "slack"
                    }
                },
                {
                    "step_number": 2,
                    "tool_name": "acc_post_comment",
                    "description": "Add automated comment to the issue",
                    "tool_parameters": {
                        "project_id": "{{trigger_data.project_id}}",
                        "issue_id": "{{trigger_data.issue.id}}",
                        "body": """🤖 **Automated Agent Notice**

This issue may be a duplicate of existing issues. Please review the following similar issues before proceeding:

{{#each trigger_data.similar_issues}}
• {{this.title}} (ID: {{this.id}}) - {{this.similarity}}% similarity
{{/each}}

**Confidence Level:** {{trigger_data.confidence}}%

If this is not a duplicate, please update the issue description or title to make it more distinctive."""
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "auto_comment",
                        "operator": "equals",
                        "value": True
                    }
                },
                {
                    "step_number": 3,
                    "tool_name": "acc_update_issue",
                    "description": "Add duplicate warning label to issue",
                    "tool_parameters": {
                        "project_id": "{{trigger_data.project_id}}",
                        "issue_id": "{{trigger_data.issue.id}}",
                        "status": "pending_review"
                    },
                    "condition": {
                        "type": "comparison",
                        "left": "{{trigger_data.confidence}}",
                        "operator": ">=",
                        "right": 85
                    }
                }
            ]
        }
    
    @staticmethod
    def incomplete_issue_alert_workflow() -> Dict[str, Any]:
        """Workflow template for incomplete issue alerts."""
        return {
            "name": "ACC Incomplete Issue Alert",
            "description": "Automatically alert teams when issues are missing required information",
            "trigger_type": "event",
            "trigger_config": {
                "event_type": "acc_issue_incomplete_detected",
                "source": "acc_ambient_agent"
            },
            "variables": {
                "notification_channels": ["slack", "email"],
                "auto_request_info": True,
                "escalate_after_hours": 24
            },
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "slack_send_message",
                    "description": "Send Slack notification about incomplete issue",
                    "tool_parameters": {
                        "channel": "{{workflow.variables.slack_channel}}",
                        "message": """⚠️ **Incomplete Issue Information**

**Project:** {{trigger_data.issue.containerId}}
**Issue:** {{trigger_data.issue.title}} (ID: {{trigger_data.issue.id}})

**Missing Fields:**
{{#each trigger_data.missing_fields}}
• {{this}}
{{/each}}

**Suggestions for Improvement:**
{{#each trigger_data.suggestions}}
• {{this}}
{{/each}}

**Action Required:** Please update the issue with missing information to ensure proper tracking and resolution.""",
                        "attachments": [
                            {
                                "color": "warning",
                                "fields": [
                                    {
                                        "title": "Missing Fields",
                                        "value": "{{trigger_data.missing_fields.length}} field(s)",
                                        "short": True
                                    },
                                    {
                                        "title": "Assigned To",
                                        "value": "{{trigger_data.issue.assignedTo}}",
                                        "short": True
                                    }
                                ]
                            }
                        ]
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "notification_channels",
                        "operator": "contains",
                        "value": "slack"
                    }
                },
                {
                    "step_number": 2,
                    "tool_name": "acc_post_comment",
                    "description": "Add information request comment to issue",
                    "tool_parameters": {
                        "project_id": "{{trigger_data.project_id}}",
                        "issue_id": "{{trigger_data.issue.id}}",
                        "body": """🤖 **Automated Agent Notice**

This issue appears to be missing some important information. To ensure proper tracking and resolution, please provide the following:

**Missing Information:**
{{#each trigger_data.missing_fields}}
• **{{this}}**
{{/each}}

**Suggestions for Improvement:**
{{#each trigger_data.suggestions}}
• {{this}}
{{/each}}

Please update the issue with the missing information. This will help ensure faster resolution and better project tracking."""
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "auto_request_info",
                        "operator": "equals",
                        "value": True
                    }
                }
            ]
        }
    
    @staticmethod
    def weekly_summary_workflow() -> Dict[str, Any]:
        """Workflow template for weekly ACC summary reports."""
        return {
            "name": "ACC Weekly Summary Report",
            "description": "Generate and distribute weekly summary of ACC issues and activity",
            "trigger_type": "scheduled",
            "trigger_config": {
                "schedule": "0 9 * * 1",  # Every Monday at 9 AM
                "timezone": "UTC"
            },
            "variables": {
                "distribution_channels": ["slack", "email"],
                "include_charts": True,
                "include_trends": True,
                "summary_period_days": 7
            },
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "acc_weekly_summary",
                    "description": "Generate weekly summary data",
                    "tool_parameters": {},
                    "timeout": 60
                },
                {
                    "step_number": 2,
                    "tool_name": "content_creation",
                    "description": "Generate formatted summary report",
                    "tool_parameters": {
                        "operation": "create_from_template",
                        "template_name": "acc_weekly_summary",
                        "variables": {
                            "summary_data": "{{step_1.summary}}",
                            "period_start": "{{step_1.summary.period.start}}",
                            "period_end": "{{step_1.summary.period.end}}",
                            "total_issues": "{{step_1.summary.totals.total_issues}}",
                            "new_issues": "{{step_1.summary.totals.new_issues}}",
                            "resolved_issues": "{{step_1.summary.totals.resolved_issues}}",
                            "open_issues": "{{step_1.summary.totals.open_issues}}"
                        }
                    }
                },
                {
                    "step_number": 3,
                    "tool_name": "slack_send_message",
                    "description": "Send summary to Slack",
                    "tool_parameters": {
                        "channel": "{{workflow.variables.report_channel}}",
                        "message": """📊 **ACC Weekly Summary Report**

**Period:** {{step_1.summary.period.start}} to {{step_1.summary.period.end}}

**📈 Overall Statistics:**
• Total Issues: {{step_1.summary.totals.total_issues}}
• New Issues: {{step_1.summary.totals.new_issues}}
• Resolved Issues: {{step_1.summary.totals.resolved_issues}}
• Open Issues: {{step_1.summary.totals.open_issues}}

**🎯 Key Insights:**
{{#each step_1.summary.insights}}
• {{this}}
{{/each}}

**📋 Project Breakdown:**
{{#each step_1.summary.projects}}
• **{{this.project_name}}**: {{this.issues_count}} issues
{{/each}}

Full detailed report available in the project dashboard.""",
                        "attachments": [
                            {
                                "color": "good",
                                "fields": [
                                    {
                                        "title": "New Issues",
                                        "value": "{{step_1.summary.totals.new_issues}}",
                                        "short": True
                                    },
                                    {
                                        "title": "Resolved Issues",
                                        "value": "{{step_1.summary.totals.resolved_issues}}",
                                        "short": True
                                    }
                                ]
                            }
                        ]
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "distribution_channels",
                        "operator": "contains",
                        "value": "slack"
                    }
                }
            ]
        }
    
    @staticmethod
    def high_priority_issue_escalation_workflow() -> Dict[str, Any]:
        """Workflow template for escalating high-priority issues."""
        return {
            "name": "ACC High Priority Issue Escalation",
            "description": "Automatically escalate high-priority issues to management",
            "trigger_type": "event",
            "trigger_config": {
                "event_type": "acc_issue_created",
                "filters": {
                    "priority": ["high", "critical"],
                    "status": ["open", "new"]
                }
            },
            "variables": {
                "escalation_channels": ["slack", "email", "teams"],
                "management_channel": "#acc-management",
                "escalation_delay_minutes": 30,
                "auto_assign_manager": True
            },
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "slack_send_message",
                    "description": "Immediate notification to management",
                    "tool_parameters": {
                        "channel": "{{workflow.variables.management_channel}}",
                        "message": """🚨 **HIGH PRIORITY ACC ISSUE**

**Project:** {{trigger_data.project_name}}
**Issue:** {{trigger_data.issue.title}}
**Priority:** {{trigger_data.issue.priority}}
**Status:** {{trigger_data.issue.status}}
**Created:** {{trigger_data.issue.createdAt}}

**Description:**
{{trigger_data.issue.description}}

**Assigned To:** {{trigger_data.issue.assignedTo}}

This issue requires immediate attention due to its high priority status.

**Action Required:** Please review and assign appropriate resources.""",
                        "attachments": [
                            {
                                "color": "danger",
                                "fields": [
                                    {
                                        "title": "Priority",
                                        "value": "{{trigger_data.issue.priority}}",
                                        "short": True
                                    },
                                    {
                                        "title": "Issue ID",
                                        "value": "{{trigger_data.issue.id}}",
                                        "short": True
                                    }
                                ]
                            }
                        ]
                    }
                },
                {
                    "step_number": 2,
                    "tool_name": "teams_send_message",
                    "description": "Send Teams notification",
                    "tool_parameters": {
                        "team_id": "{{workflow.variables.management_team_id}}",
                        "channel_id": "{{workflow.variables.management_teams_channel}}",
                        "message": {
                            "type": "AdaptiveCard",
                            "body": [
                                {
                                    "type": "TextBlock",
                                    "text": "🚨 HIGH PRIORITY ACC ISSUE",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                    "color": "Attention"
                                },
                                {
                                    "type": "FactSet",
                                    "facts": [
                                        {
                                            "title": "Project:",
                                            "value": "{{trigger_data.project_name}}"
                                        },
                                        {
                                            "title": "Issue:",
                                            "value": "{{trigger_data.issue.title}}"
                                        },
                                        {
                                            "title": "Priority:",
                                            "value": "{{trigger_data.issue.priority}}"
                                        },
                                        {
                                            "title": "Assigned To:",
                                            "value": "{{trigger_data.issue.assignedTo}}"
                                        }
                                    ]
                                }
                            ],
                            "actions": [
                                {
                                    "type": "Action.OpenUrl",
                                    "title": "View Issue",
                                    "url": "{{trigger_data.issue_url}}"
                                }
                            ]
                        }
                    },
                    "condition": {
                        "type": "variable_check",
                        "variable": "escalation_channels",
                        "operator": "contains",
                        "value": "teams"
                    }
                }
            ]
        }
    
    @staticmethod
    def get_all_templates() -> List[Dict[str, Any]]:
        """Get all available ACC workflow templates."""
        return [
            ACCWorkflowTemplates.duplicate_issue_alert_workflow(),
            ACCWorkflowTemplates.incomplete_issue_alert_workflow(),
            ACCWorkflowTemplates.weekly_summary_workflow(),
            ACCWorkflowTemplates.high_priority_issue_escalation_workflow()
        ]
    
    @staticmethod
    def create_template_for_user(template_name: str, user_id: int, custom_variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a workflow template instance for a specific user."""
        templates = {
            "duplicate_alert": ACCWorkflowTemplates.duplicate_issue_alert_workflow,
            "incomplete_alert": ACCWorkflowTemplates.incomplete_issue_alert_workflow,
            "weekly_summary": ACCWorkflowTemplates.weekly_summary_workflow,
            "high_priority_escalation": ACCWorkflowTemplates.high_priority_issue_escalation_workflow
        }
        
        if template_name not in templates:
            raise ValueError(f"Unknown template: {template_name}")
            
        template = templates[template_name]()
        
        # Customize for user
        if custom_variables:
            template["variables"].update(custom_variables)
            
        # Add user context
        template["user_id"] = user_id
        template["created_from_template"] = template_name
        
        return template
