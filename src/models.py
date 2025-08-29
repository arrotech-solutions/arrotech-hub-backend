"""
Database models for Mini-Hub MCP Server.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class SubscriptionTier(str, Enum):
    """Subscription tiers."""
    FREE = "free"
    TESTING = "testing"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ConnectionStatus(str, Enum):
    """Connection status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"


class ConnectionPlatform(str, Enum):
    """Connection platforms."""
    HUBSPOT = "hubspot"
    GA4 = "ga4"
    SLACK = "slack"
    POWERBI = "powerbi"
    ACC = "acc"


class MessageRole(str, Enum):
    """Message roles in conversations."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(str, Enum):
    """Message status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class WorkflowStatus(str, Enum):
    """Workflow status."""
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class WorkflowExecutionStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowTriggerType(str, Enum):
    """Workflow trigger types."""
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"
    WEBHOOK = "webhook"


class User(Base):
    """User model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    api_key = Column(String, unique=True, index=True, nullable=True)
    subscription_tier = Column(String, default=SubscriptionTier.FREE)
    stripe_customer_id = Column(String, nullable=True)
    
    # Password reset fields
    password_reset_token = Column(String, nullable=True)
    password_reset_expires = Column(DateTime(timezone=True), nullable=True)
    
    # Remember me functionality
    remember_me_token = Column(String, nullable=True)
    remember_me_expires = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    usage_logs = relationship("UsageLog", back_populates="user")
    connections = relationship("Connection", back_populates="user")
    settings = relationship(
        "UserSettings", back_populates="user", uselist=False)
    conversations = relationship("Conversation", back_populates="user")
    workflows = relationship("Workflow", back_populates="user")
    workflow_executions = relationship("WorkflowExecution", back_populates="user")


class Conversation(Base):
    """Conversation model for chat sessions."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=True)  # Auto-generated from first message
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    """Message model for chat messages."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey(
        "conversations.id"), nullable=False)
    role = Column(String, nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)
    status = Column(String, default=MessageStatus.COMPLETED)
    tokens_used = Column(Integer, nullable=True)
    tools_called = Column(JSON, nullable=True)  # List of tools used
    tool_call_id = Column(String, nullable=True)  # ID of the tool call this message responds to
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class Workflow(Base):
    """Workflow model for storing business automation workflows."""
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default=WorkflowStatus.DRAFT)
    version = Column(Integer, default=1)
    is_template = Column(Boolean, default=False)
    trigger_type = Column(String, default=WorkflowTriggerType.MANUAL)
    trigger_config = Column(JSON, nullable=True)  # Schedule, webhook URL, etc.
    variables = Column(JSON, nullable=True)  # Workflow variables and defaults
    workflow_metadata = Column(JSON, nullable=True)  # Additional workflow metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="workflows")
    steps = relationship("WorkflowStep", back_populates="workflow", order_by="WorkflowStep.step_number")
    executions = relationship("WorkflowExecution", back_populates="workflow")


class WorkflowStep(Base):
    """Workflow step model for individual workflow steps."""
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    tool_name = Column(String, nullable=False)
    tool_parameters = Column(JSON, nullable=True)  # Parameters for the tool
    description = Column(Text, nullable=True)
    condition = Column(JSON, nullable=True)  # Conditional logic for step execution
    retry_config = Column(JSON, nullable=True)  # Retry settings
    timeout = Column(Integer, nullable=True)  # Step timeout in seconds
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="steps")


class WorkflowExecution(Base):
    """Workflow execution model for tracking workflow runs."""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default=WorkflowExecutionStatus.PENDING)
    trigger_type = Column(String, default=WorkflowTriggerType.MANUAL)
    trigger_data = Column(JSON, nullable=True)  # Data that triggered the execution
    input_data = Column(JSON, nullable=True)  # Input data for the workflow
    output_data = Column(JSON, nullable=True)  # Output data from the workflow
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="executions")
    user = relationship("User", back_populates="workflow_executions")
    step_executions = relationship("WorkflowStepExecution", back_populates="workflow_execution")


class WorkflowStepExecution(Base):
    """Workflow step execution model for tracking individual step runs."""
    __tablename__ = "workflow_step_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_execution_id = Column(Integer, ForeignKey("workflow_executions.id"), nullable=False)
    step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    status = Column(String, default=WorkflowExecutionStatus.PENDING)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workflow_execution = relationship("WorkflowExecution", back_populates="step_executions")
    step = relationship("WorkflowStep")


class UserSettings(Base):
    """User settings model for storing user preferences and configurations."""
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"),
                     nullable=False, unique=True)

    # Notification Settings
    email_notifications = Column(Boolean, default=True)
    slack_notifications = Column(Boolean, default=False)
    webhook_notifications = Column(Boolean, default=False)
    notification_webhook_url = Column(String, nullable=True)

    # API Settings
    api_rate_limit = Column(Integer, default=1000)  # requests per hour
    api_timeout = Column(Integer, default=30)  # seconds
    auto_refresh_tokens = Column(Boolean, default=True)

    # Dashboard Settings
    dashboard_theme = Column(String, default="light")  # light, dark, auto
    dashboard_layout = Column(String, default="default")  # default, compact
    show_analytics = Column(Boolean, default=True)
    show_usage_stats = Column(Boolean, default=True)

    # Integration Settings
    auto_sync_connections = Column(Boolean, default=True)
    sync_frequency = Column(String, default="hourly")  # hourly, daily, weekly
    backup_connections = Column(Boolean, default=True)

    # Security Settings
    two_factor_enabled = Column(Boolean, default=False)
    session_timeout = Column(Integer, default=30)  # minutes
    ip_whitelist = Column(JSON, nullable=True)  # List of allowed IPs

    # Custom Settings
    custom_settings = Column(JSON, nullable=True)  # User-defined settings

    # Power BI Settings
    powerbi_auto_refresh = Column(Boolean, default=True)
    powerbi_default_workspace = Column(String, nullable=True)
    powerbi_embed_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="settings")


class Connection(Base):
    """Connection model for marketing tool integrations."""
    __tablename__ = "connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(String, nullable=False)  # hubspot, ga4, slack
    name = Column(String, nullable=False)
    status = Column(String, default=ConnectionStatus.PENDING)
    config = Column(JSON, nullable=True)  # API keys, settings, etc.
    last_sync = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="connections")


class Subscription(Base):
    """Subscription model."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stripe_subscription_id = Column(String, nullable=True)
    tier = Column(String, nullable=False)
    status = Column(String, default="active")
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")


class UsageLog(Base):
    """Usage log model."""
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments = Column(Text, nullable=True)  # JSON string
    response_time_ms = Column(Integer, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="usage_logs")


class Payment(Base):
    """Payment model for tracking transactions."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_method = Column(String, nullable=False)  # mpesa, stripe
    amount = Column(Integer, nullable=False)  # Amount in cents
    currency = Column(String, default="KES")
    status = Column(String, default="pending")  # pending, completed, failed
    transaction_id = Column(String, nullable=True)
    reference = Column(String, nullable=True)
    payment_metadata = Column(JSON, nullable=True)  # Additional payment data
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User")


class Task(BaseModel):
    """Represents a single task in a task plan."""
    id: int
    objective: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = {}
    dependencies: List[int] = []
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class TaskPlan(BaseModel):
    """Represents a complete task plan for a user request."""
    id: str
    user_request: str
    tasks: List[Task]
    execution_order: List[int]
    status: str = "pending"  # pending, running, completed, failed
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

class IntentClassifier(BaseModel):
    """Represents the classification of user intent."""
    intent_type: str  # chat, action, query, analysis, automation
    confidence: float
    requires_tools: bool
    suggested_tools: List[str] = []
    explanation: Optional[str] = None
