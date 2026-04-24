"""
Tests for src/models.py — Enum values, Pydantic model validation, and SQLAlchemy model structure.
"""
import pytest


class TestEnums:
    """Verify every Enum class has the expected members."""

    def test_subscription_tier(self):
        from src.models import SubscriptionTier
        assert SubscriptionTier.FREE == "free"
        assert SubscriptionTier.STARTER == "starter"
        assert SubscriptionTier.BUSINESS == "business"
        assert SubscriptionTier.PRO == "pro"
        assert SubscriptionTier.ENTERPRISE == "enterprise"
        assert len(SubscriptionTier) == 5

    def test_user_role(self):
        from src.models import UserRole
        assert UserRole.USER == "user"
        assert UserRole.EMPLOYEE == "employee"
        assert UserRole.ADMIN == "admin"

    def test_connection_status(self):
        from src.models import ConnectionStatus
        assert ConnectionStatus.ACTIVE == "active"
        assert ConnectionStatus.INACTIVE == "inactive"
        assert ConnectionStatus.ERROR == "error"
        assert ConnectionStatus.PENDING == "pending"

    def test_connection_platform(self):
        from src.models import ConnectionPlatform
        assert ConnectionPlatform.HUBSPOT == "hubspot"
        assert ConnectionPlatform.SLACK == "slack"
        assert ConnectionPlatform.GA4 == "ga4"
        assert ConnectionPlatform.LINKEDIN == "linkedin"

    def test_message_role(self):
        from src.models import MessageRole
        assert MessageRole.USER == "user"
        assert MessageRole.ASSISTANT == "assistant"
        assert MessageRole.SYSTEM == "system"
        assert MessageRole.TOOL == "tool"

    def test_message_status(self):
        from src.models import MessageStatus
        assert MessageStatus.PENDING == "pending"
        assert MessageStatus.PROCESSING == "processing"
        assert MessageStatus.COMPLETED == "completed"
        assert MessageStatus.ERROR == "error"

    def test_workflow_status(self):
        from src.models import WorkflowStatus
        assert WorkflowStatus.DRAFT == "draft"
        assert WorkflowStatus.ACTIVE == "active"
        assert WorkflowStatus.INACTIVE == "inactive"
        assert WorkflowStatus.ARCHIVED == "archived"

    def test_workflow_execution_status(self):
        from src.models import WorkflowExecutionStatus
        assert WorkflowExecutionStatus.PENDING == "pending"
        assert WorkflowExecutionStatus.RUNNING == "running"
        assert WorkflowExecutionStatus.COMPLETED == "completed"
        assert WorkflowExecutionStatus.FAILED == "failed"
        assert WorkflowExecutionStatus.CANCELLED == "cancelled"

    def test_workflow_trigger_type(self):
        from src.models import WorkflowTriggerType
        assert WorkflowTriggerType.MANUAL == "manual"
        assert WorkflowTriggerType.SCHEDULED == "scheduled"
        assert WorkflowTriggerType.WEBHOOK == "webhook"
        assert WorkflowTriggerType.EVENT == "event"

    def test_workflow_visibility(self):
        from src.models import WorkflowVisibility
        assert WorkflowVisibility.PRIVATE == "private"
        assert WorkflowVisibility.UNLISTED == "unlisted"
        assert WorkflowVisibility.PUBLIC == "public"
        assert WorkflowVisibility.MARKETPLACE == "marketplace"

    def test_workflow_license(self):
        from src.models import WorkflowLicense
        assert WorkflowLicense.FREE == "free"
        assert WorkflowLicense.PERSONAL == "personal"
        assert WorkflowLicense.COMMERCIAL == "commercial"
        assert WorkflowLicense.ENTERPRISE == "enterprise"

    def test_access_request_status(self):
        from src.models import AccessRequestStatus
        assert AccessRequestStatus.PENDING == "pending"
        assert AccessRequestStatus.APPROVED == "approved"
        assert AccessRequestStatus.REJECTED == "rejected"

    def test_invoice_status(self):
        from src.models import InvoiceStatus
        assert InvoiceStatus.DRAFT == "draft"
        assert InvoiceStatus.SENT == "sent"
        assert InvoiceStatus.PAID == "paid"
        assert InvoiceStatus.PARTIAL == "partial"
        assert InvoiceStatus.OVERDUE == "overdue"
        assert InvoiceStatus.CANCELLED == "cancelled"

    def test_subscription_status(self):
        from src.models import SubscriptionStatus
        assert SubscriptionStatus.ACTIVE == "active"
        assert SubscriptionStatus.PAST_DUE == "past_due"
        assert SubscriptionStatus.CANCELED == "canceled"
        assert SubscriptionStatus.EXPIRED == "expired"
        assert SubscriptionStatus.GRACE_PERIOD == "grace_period"

    def test_whatsapp_message_direction(self):
        from src.models import WhatsAppMessageDirection
        assert WhatsAppMessageDirection.INCOMING == "incoming"
        assert WhatsAppMessageDirection.OUTGOING == "outgoing"

    def test_whatsapp_message_status(self):
        from src.models import WhatsAppMessageStatus
        assert WhatsAppMessageStatus.PENDING == "pending"
        assert WhatsAppMessageStatus.SENT == "sent"
        assert WhatsAppMessageStatus.DELIVERED == "delivered"
        assert WhatsAppMessageStatus.READ == "read"
        assert WhatsAppMessageStatus.FAILED == "failed"

    def test_whatsapp_auto_reply_trigger(self):
        from src.models import WhatsAppAutoReplyTrigger
        assert WhatsAppAutoReplyTrigger.FIRST_MESSAGE == "first_message"
        assert WhatsAppAutoReplyTrigger.KEYWORD == "keyword"
        assert WhatsAppAutoReplyTrigger.BUSINESS_HOURS == "business_hours"
        assert WhatsAppAutoReplyTrigger.ALL == "all"

    def test_org_role(self):
        from src.models import OrgRole
        assert OrgRole.OWNER == "owner"
        assert OrgRole.ADMIN == "admin"
        assert OrgRole.MEMBER == "member"
        assert OrgRole.VIEWER == "viewer"

    def test_org_invitation_status(self):
        from src.models import OrgInvitationStatus
        assert OrgInvitationStatus.PENDING == "pending"
        assert OrgInvitationStatus.ACCEPTED == "accepted"
        assert OrgInvitationStatus.DECLINED == "declined"
        assert OrgInvitationStatus.EXPIRED == "expired"

    def test_notification_type(self):
        from src.models import NotificationType
        assert NotificationType.WORKFLOW_IMPORTED == "workflow_imported"
        assert NotificationType.SYSTEM_ANNOUNCEMENT == "system_announcement"

    def test_enum_string_inheritance(self):
        from src.models import SubscriptionTier, UserRole, ConnectionStatus
        assert isinstance(SubscriptionTier.FREE, str)
        assert isinstance(UserRole.USER, str)
        assert isinstance(ConnectionStatus.ACTIVE, str)


class TestPydanticModels:
    def test_task_creation(self):
        from src.models import Task
        task = Task(id=1, objective="Test objective")
        assert task.id == 1
        assert task.objective == "Test objective"
        assert task.status == "pending"
        assert task.tool_name is None
        assert task.arguments == {}
        assert task.dependencies == []

    def test_task_with_all_fields(self):
        from src.models import Task
        task = Task(id=2, objective="Run tool", tool_name="slack_send",
                    arguments={"channel": "#gen"}, dependencies=[1],
                    status="completed", result={"ok": True}, error=None)
        assert task.tool_name == "slack_send"
        assert task.dependencies == [1]

    def test_task_with_error(self):
        from src.models import Task
        task = Task(id=3, objective="Fail", status="failed", error="Connection refused")
        assert task.error == "Connection refused"

    def test_task_plan_creation(self):
        from src.models import TaskPlan, Task
        plan = TaskPlan(id="plan-1", user_request="Send email",
                        tasks=[Task(id=1, objective="draft")], execution_order=[1])
        assert plan.id == "plan-1"
        assert len(plan.tasks) == 1
        assert plan.status == "pending"

    def test_intent_classifier(self):
        from src.models import IntentClassifier
        ic = IntentClassifier(intent_type="action", confidence=0.95,
                              requires_tools=True, suggested_tools=["slack_send"])
        assert ic.intent_type == "action"
        assert ic.confidence == 0.95
        assert ic.requires_tools is True

    def test_intent_classifier_defaults(self):
        from src.models import IntentClassifier
        ic = IntentClassifier(intent_type="chat", confidence=0.5, requires_tools=False)
        assert ic.suggested_tools == []
        assert ic.explanation is None


class TestSQLAlchemyModels:
    def test_user_tablename(self):
        from src.models import User
        assert User.__tablename__ == "users"

    def test_conversation_tablename(self):
        from src.models import Conversation
        assert Conversation.__tablename__ == "conversations"

    def test_workflow_tablename(self):
        from src.models import Workflow
        assert Workflow.__tablename__ == "workflows"

    def test_connection_tablename(self):
        from src.models import Connection
        assert Connection.__tablename__ == "connections"

    def test_notification_tablename(self):
        from src.models import Notification
        assert Notification.__tablename__ == "notifications"

    def test_mpesa_payment_tablename(self):
        from src.models import MpesaPayment
        assert MpesaPayment.__tablename__ == "mpesa_payments"

    def test_invoice_tablename(self):
        from src.models import Invoice
        assert Invoice.__tablename__ == "invoices"

    def test_access_request_tablename(self):
        from src.models import AccessRequest
        assert AccessRequest.__tablename__ == "access_requests"

    def test_whatsapp_contact_tablename(self):
        from src.models import WhatsAppContact
        assert WhatsAppContact.__tablename__ == "whatsapp_contacts"

    def test_whatsapp_message_tablename(self):
        from src.models import WhatsAppMessage
        assert WhatsAppMessage.__tablename__ == "whatsapp_messages"

    def test_user_has_key_columns(self):
        from src.models import User
        assert hasattr(User, 'email')
        assert hasattr(User, 'name')
        assert hasattr(User, 'password_hash')
        assert hasattr(User, 'subscription_tier')
        assert hasattr(User, 'role')
        assert hasattr(User, 'email_verified')

    def test_workflow_has_marketplace_columns(self):
        from src.models import Workflow
        assert hasattr(Workflow, 'visibility')
        assert hasattr(Workflow, 'share_code')
        assert hasattr(Workflow, 'price')
        assert hasattr(Workflow, 'downloads_count')
