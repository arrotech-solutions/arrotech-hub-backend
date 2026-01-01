"""
Database models for Mini-Hub MCP Server.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Numeric
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
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


class WorkflowVisibility(str, Enum):
    """Workflow visibility options."""
    PRIVATE = "private"      # Only visible to creator
    UNLISTED = "unlisted"    # Shareable via link
    PUBLIC = "public"        # Visible in gallery
    MARKETPLACE = "marketplace"  # Listed for sale


class WorkflowLicense(str, Enum):
    """Workflow license types."""
    FREE = "free"                # Free to use
    PERSONAL = "personal"        # Personal use only
    COMMERCIAL = "commercial"    # Commercial use allowed
    ENTERPRISE = "enterprise"    # Enterprise licensing


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
    workflow_downloads = relationship("WorkflowDownload", back_populates="user")
    workflow_reviews = relationship("WorkflowReview", back_populates="user")
    creator_profile = relationship("CreatorProfile", back_populates="user", uselist=False)


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
    
    # Sharing & Marketplace fields
    visibility = Column(String, default=WorkflowVisibility.PRIVATE)  # Visibility level
    share_code = Column(String, unique=True, nullable=True, index=True)  # Unique share code for unlisted
    license_type = Column(String, default=WorkflowLicense.FREE)  # License type
    price = Column(Integer, nullable=True)  # Price in cents (nullable for free)
    currency = Column(String, default="USD")  # Currency code
    category = Column(String, nullable=True)  # Category for marketplace
    tags = Column(JSON, nullable=True)  # Tags for search/filtering
    required_connections = Column(JSON, nullable=True)  # List of required platform connections
    downloads_count = Column(Integer, default=0)  # Number of downloads/imports
    rating_sum = Column(Integer, default=0)  # Sum of all ratings
    rating_count = Column(Integer, default=0)  # Number of ratings
    author_name = Column(String, nullable=True)  # Display name for marketplace
    preview_image = Column(String, nullable=True)  # Preview image URL

    # Relationships
    user = relationship("User", back_populates="workflows")
    steps = relationship("WorkflowStep", back_populates="workflow", order_by="WorkflowStep.step_number", cascade="all, delete-orphan")
    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")
    downloads = relationship("WorkflowDownload", back_populates="workflow", cascade="all, delete-orphan")
    reviews = relationship("WorkflowReview", back_populates="workflow", cascade="all, delete-orphan")
    versions = relationship("WorkflowVersion", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowVersion.version_number.desc()")


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
    step_executions = relationship("WorkflowStepExecution", back_populates="step", cascade="all, delete-orphan")


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
    step_executions = relationship("WorkflowStepExecution", back_populates="workflow_execution", cascade="all, delete-orphan")


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
    step = relationship("WorkflowStep", back_populates="step_executions")


class WorkflowDownload(Base):
    """Tracks workflow downloads/imports by users."""
    __tablename__ = "workflow_downloads"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    downloaded_at = Column(DateTime(timezone=True), server_default=func.now())
    source_version = Column(Integer, default=1)  # Version at time of download
    imported_workflow_id = Column(Integer, nullable=True)  # If user imported to their own workflows

    # Relationships
    workflow = relationship("Workflow", back_populates="downloads")
    user = relationship("User", back_populates="workflow_downloads")


class WorkflowReview(Base):
    """User reviews for shared workflows."""
    __tablename__ = "workflow_reviews"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    title = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    helpful_count = Column(Integer, default=0)  # Number of "helpful" votes
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="reviews")
    user = relationship("User", back_populates="workflow_reviews")


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


class CreatorProfile(Base):
    """Creator profile for marketplace authors."""
    __tablename__ = "creator_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Profile information
    display_name = Column(String, nullable=False)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    website = Column(String, nullable=True)
    github_url = Column(String, nullable=True)
    twitter_url = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    
    # Verification and badges
    is_verified = Column(Boolean, default=False)
    verification_date = Column(DateTime(timezone=True), nullable=True)
    badges = Column(JSON, nullable=True)  # e.g., ["top_creator", "expert", "early_adopter"]
    
    # Statistics (computed/cached)
    total_workflows = Column(Integer, default=0)
    total_downloads = Column(Integer, default=0)
    total_reviews = Column(Integer, default=0)
    average_rating = Column(Numeric(3, 2), default=0)
    total_earnings = Column(Numeric(10, 2), default=0)
    
    # Payout information
    payout_method = Column(String, nullable=True)  # stripe, mpesa, paypal
    payout_details = Column(JSON, nullable=True)  # Encrypted payout details
    
    # Settings
    is_public = Column(Boolean, default=True)
    accept_donations = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="creator_profile")


class WorkflowVersion(Base):
    """Track workflow versions for updates and rollbacks."""
    __tablename__ = "workflow_versions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    
    # Snapshot of workflow at this version
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    steps_snapshot = Column(JSON, nullable=False)  # Full copy of steps
    variables_snapshot = Column(JSON, nullable=True)
    trigger_config_snapshot = Column(JSON, nullable=True)
    
    # Version metadata
    changelog = Column(Text, nullable=True)  # What changed in this version
    is_breaking = Column(Boolean, default=False)  # Breaking changes flag
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    workflow = relationship("Workflow", back_populates="versions")


class WorkflowAnalytics(Base):
    """Analytics tracking for marketplace workflows."""
    __tablename__ = "workflow_analytics"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Daily aggregated metrics
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # View metrics
    impressions = Column(Integer, default=0)  # Times shown in browse/search
    detail_views = Column(Integer, default=0)  # Times details modal opened
    unique_viewers = Column(Integer, default=0)  # Unique users who viewed
    
    # Conversion metrics  
    import_clicks = Column(Integer, default=0)  # Times import button clicked
    successful_imports = Column(Integer, default=0)  # Successful imports
    
    # Engagement metrics
    review_clicks = Column(Integer, default=0)  # Times review section viewed
    share_clicks = Column(Integer, default=0)  # Times share button clicked
    
    # Search metrics
    search_appearances = Column(Integer, default=0)  # Times appeared in search
    search_clicks = Column(Integer, default=0)  # Times clicked from search
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Unique constraint on workflow_id + date
    __table_args__ = (
        Index('ix_workflow_analytics_workflow_date', 'workflow_id', 'date', unique=True),
    )


class NotificationType(str, Enum):
    """Types of notifications."""
    WORKFLOW_IMPORTED = "workflow_imported"
    WORKFLOW_REVIEWED = "workflow_reviewed"
    WORKFLOW_RATED = "workflow_rated"
    NEW_FOLLOWER = "new_follower"
    MILESTONE_REACHED = "milestone_reached"
    SYSTEM_ANNOUNCEMENT = "system_announcement"
    EARNINGS_RECEIVED = "earnings_received"


class Notification(Base):
    """In-app notifications for users."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Notification content
    notification_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    
    # Related entities
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # User who triggered
    
    # Extra data
    extra_data = Column(JSON, nullable=True)  # Additional data (e.g., rating value, download count)
    
    # Status
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    
    # Action URL
    action_url = Column(String, nullable=True)  # Where to navigate on click
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    workflow = relationship("Workflow")
    actor = relationship("User", foreign_keys=[actor_id])


class WorkflowFavorite(Base):
    """User's favorite/bookmarked workflows."""
    __tablename__ = "workflow_favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_workflow_favorites_unique', 'user_id', 'workflow_id', unique=True),
    )

    # Relationships
    user = relationship("User", backref="favorites")
    workflow = relationship("Workflow", backref="favorited_by")


class UserPreferences(Base):
    """User preferences for notifications and app behavior."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Email notification preferences
    email_on_download = Column(Boolean, default=True)
    email_on_sale = Column(Boolean, default=True)
    email_on_review = Column(Boolean, default=True)
    email_on_follower = Column(Boolean, default=True)
    email_weekly_summary = Column(Boolean, default=True)
    
    # In-app notification preferences
    notify_on_download = Column(Boolean, default=True)
    notify_on_sale = Column(Boolean, default=True)
    notify_on_review = Column(Boolean, default=True)
    notify_on_follower = Column(Boolean, default=True)
    
    # App preferences
    theme = Column(String, default="system")  # light, dark, system
    language = Column(String, default="en")
    timezone = Column(String, default="UTC")
    default_visibility = Column(String, default="private")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="preferences")


class CreatorFollower(Base):
    """Follower relationship between users."""
    __tablename__ = "creator_followers"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Unique constraint: a user can only follow another user once
    __table_args__ = (
        Index('ix_creator_followers_unique', 'follower_id', 'following_id', unique=True),
    )

    # Relationships
    follower = relationship("User", foreign_keys=[follower_id], backref="following")
    following = relationship("User", foreign_keys=[following_id], backref="followers")


class ActivityFeedItem(Base):
    """Activity feed for followed creators."""
    __tablename__ = "activity_feed"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Activity type and content
    activity_type = Column(String, nullable=False)  # workflow_published, workflow_updated, milestone, etc.
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # Related entities
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    
    # Extra data
    extra_data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    actor = relationship("User", foreign_keys=[actor_id])
    workflow = relationship("Workflow")


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
