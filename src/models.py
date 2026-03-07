"""
Database models for Mini-Hub MCP Server.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Numeric, Float
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class SubscriptionTier(str, Enum):
    """Subscription tiers - Kenya-first Arrotech Hub pricing."""
    FREE = "free"           # KES 0 - Unified Visibility
    STARTER = "starter"     # KES 1,500 - Unified Action
    BUSINESS = "business"   # KES 5,000 - Unified Operations
    PRO = "pro"             # KES 10,000 - Unified Command Center (Agency)
    ENTERPRISE = "enterprise"  # Custom pricing


class UserRole(str, Enum):
    """User roles for access control."""
    USER = "user"
    EMPLOYEE = "employee"
    ADMIN = "admin"


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


class AccessRequestStatus(str, Enum):
    """Status for platform access requests."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InvoiceStatus(str, Enum):
    """Invoice status."""
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"



class SubscriptionStatus(str, Enum):
    """Subscription status."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    GRACE_PERIOD = "grace_period"


class WhatsAppMessageDirection(str, Enum):
    """WhatsApp message direction."""
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class WhatsAppMessageStatus(str, Enum):
    """WhatsApp message delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class WhatsAppAutoReplyTrigger(str, Enum):
    """Auto-reply trigger types."""
    FIRST_MESSAGE = "first_message"  # First time contact messages
    KEYWORD = "keyword"  # Contains specific keywords
    BUSINESS_HOURS = "business_hours"  # Outside business hours
    ALL = "all"  # Respond to all messages (AI mode)


class OrgRole(str, Enum):
    """Organization member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class OrgInvitationStatus(str, Enum):
    """Organization invitation status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


class User(Base):
    """User model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    api_key = Column(String, unique=True, index=True, nullable=True)
    subscription_tier = Column(String, default=SubscriptionTier.FREE)
    subscription_status = Column(String, default=SubscriptionStatus.ACTIVE)
    subscription_end_date = Column(DateTime(timezone=True), nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    paystack_customer_code = Column(String, nullable=True)  # NEW: For Paystack
    paystack_authorization_code = Column(String, nullable=True)  # NEW: For recurring charges
    role = Column(String, nullable=True, default=UserRole.USER)  # user, employee, admin
    permissions = Column(JSON, nullable=True)  # Employee permissions dict
    login_challenge = Column(String, nullable=True)  # Challenge for WebAuthn in-flight authentication
    login_otp = Column(String, nullable=True)  # Temporary Email 2FA OTP code
    login_otp_expiry = Column(DateTime(timezone=True), nullable=True)  # Expiry time for the OPT
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
    tiktok_profile = relationship("TikTokProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    webauthn_credentials = relationship("WebAuthnCredential", back_populates="user", cascade="all, delete-orphan")
    organization_memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")


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
    openai_api_key = Column(String, nullable=True)  # User provided OpenAI Key
    anthropic_api_key = Column(String, nullable=True)  # User provided Anthropic Key
    gemini_api_key = Column(String, nullable=True)  # User provided Gemini Key
    huggingface_api_key = Column(String, nullable=True)  # User provided Hugging Face Key
    together_api_key = Column(String, nullable=True)  # User provided Together AI Key

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
    email_2fa_enabled = Column(Boolean, default=False)
    default_2fa_method = Column(String, default="totp") # "totp" or "email"
    totp_secret = Column(String, nullable=True)  # For TOTP authentication
    backup_codes = Column(JSON, nullable=True)  # Hashed backup codes
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


class WebAuthnCredential(Base):
    """WebAuthn credentials (Passkeys) for a user."""
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id = Column(String, unique=True, index=True, nullable=False)
    public_key = Column(String, nullable=False)
    sign_count = Column(Integer, default=0)
    transports = Column(JSON, nullable=True)
    name = Column(String, nullable=True)  # e.g., "iPhone", "YubiKey"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="webauthn_credentials")


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


class UsageRecord(Base):
    """
    Monthly usage records for AI actions and automation runs.
    Tracks usage against plan limits for feature gating.
    """
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Period tracking (monthly)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)
    
    # Usage counters
    ai_actions_count = Column(Integer, default=0)
    automation_runs_count = Column(Integer, default=0)
    
    # Limit tracking (snapshot of plan limits at period start)
    ai_actions_limit = Column(Integer, nullable=False)
    automation_runs_limit = Column(Integer, nullable=False)
    
    # Warning flags
    ai_warning_sent = Column(Boolean, default=False)  # 80% threshold
    automation_warning_sent = Column(Boolean, default=False)  # 80% threshold
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Unique constraint on user + period
    __table_args__ = (
        Index('ix_usage_records_user_period', 'user_id', 'period_start', unique=True),
    )

    # Relationships
    user = relationship("User", backref="usage_records")


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


class MpesaPayment(Base):
    """M-Pesa payment record for business reconciliation."""
    __tablename__ = "mpesa_payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    transaction_id = Column(String, unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    phone_number = Column(String(20), nullable=False)
    reference = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    transaction_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)  # pending, matched, unmatched, verified
    matched_invoice_id = Column(Integer, nullable=True)
    match_confidence = Column(Float, nullable=True)
    channel = Column(String, nullable=True)
    
    # Fraud Detection Fields
    is_suspicious = Column(Boolean, default=False, index=True)
    fraud_risk_score = Column(Float, nullable=True)  # 0.0 - 1.0
    fraud_flags = Column(JSON, nullable=True)  # List of triggered fraud rules
    verification_status = Column(String, default="unverified")  # unverified, verified, failed
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="mpesa_payments")
    locked_by_user = relationship("User", foreign_keys=[locked_by])


class MpesaAgentConfig(Base):
    """M-Pesa agent configuration per user."""
    __tablename__ = "mpesa_agent_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    alert_channel_id = Column(String, nullable=True)
    alert_enabled = Column(Boolean, default=True, nullable=False)
    auto_match_enabled = Column(Boolean, default=True, nullable=False)
    match_threshold = Column(Float, default=0.8, nullable=False)
    notification_preferences = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="mpesa_agent_config")


class Invoice(Base):
    """Invoice model for reconciliation."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invoice_number = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default=InvoiceStatus.SENT, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    reference = Column(String, nullable=True)  # External reference (e.g., matching M-Pesa account)
    description = Column(Text, nullable=True)
    items = Column(JSON, nullable=True)  # List of items
    metadata_ = Column(JSON, nullable=True)  # Additional metadata (renamed from metadata to avoid conflict)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Unique constraint on user_id + invoice_number
    __table_args__ = (
        Index('ix_invoices_user_number', 'user_id', 'invoice_number', unique=True),
    )

    # Relationships
    user = relationship("User", backref="invoices")


class FraudSignal(Base):
    """Track fraud indicators for machine learning."""
    __tablename__ = "fraud_signals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("mpesa_payments.id"), nullable=True, index=True)
    
    # Signal metadata
    signal_type = Column(String, index=True)  # duplicate, frequency, amount_anomaly, time_anomaly, staff_pattern
    risk_score = Column(Numeric(3, 2))  # 0.00 - 1.00
    confidence = Column(Numeric(3, 2))  # How confident we are in this signal
    
    # Detection details
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    detection_method = Column(String)  # rule_based, ml_model, manual
    
    # Context (store additional detection info)
    metadata_ = Column(JSON, nullable=True)
    
    # Human review
    is_false_positive = Column(Boolean, default=False, index=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Action taken
    action_taken = Column(String, nullable=True)  # locked, flagged, approved, dismissed
    notes = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="fraud_signals")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    payment = relationship("MpesaPayment", backref="fraud_signals")


class AccessRequest(Base):
    """Model for tracking early access/waitlist requests."""
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    status = Column(String, default=AccessRequestStatus.PENDING)
    reason = Column(Text, nullable=True)  # Optional: Why they want access
    request_metadata = Column(JSON, nullable=True)  # Source, referer, etc.
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ============================================================================
# WhatsApp Integration Models - For viral auto-reply and chatbot features
# ============================================================================

class WhatsAppContact(Base):
    """WhatsApp contact/customer model."""
    __tablename__ = "whatsapp_contacts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    phone_number = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)  # User-assigned name
    profile_name = Column(String, nullable=True)  # From WhatsApp profile
    
    # Contact metadata
    tags = Column(JSON, nullable=True)  # ["vip", "new-customer", "lead"]
    notes = Column(Text, nullable=True)
    metadata_ = Column(JSON, nullable=True)  # Custom fields
    
    # Engagement tracking
    first_message_at = Column(DateTime(timezone=True), nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, default=0)
    is_blocked = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", backref="whatsapp_contacts")
    messages = relationship("WhatsAppMessage", back_populates="contact", order_by="WhatsAppMessage.created_at.desc()")
    
    # Unique constraint: one phone per user
    __table_args__ = (
        UniqueConstraint("user_id", "phone_number", name="uix_user_phone"),
        Index("ix_whatsapp_contacts_user_last_msg", "user_id", "last_message_at"),
    )


class WhatsAppMessage(Base):
    """WhatsApp message model for conversation history."""
    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False, index=True)
    
    # Message details
    direction = Column(String, nullable=False)  # incoming/outgoing
    message_type = Column(String, default="text")  # text, image, video, document, location, template
    content = Column(Text, nullable=True)  # Text content or caption
    media_url = Column(String, nullable=True)  # URL for media messages
    media_mime_type = Column(String, nullable=True)
    
    # WhatsApp IDs
    whatsapp_message_id = Column(String, unique=True, index=True, nullable=True)
    context_message_id = Column(String, nullable=True)  # Reply-to message ID
    
    # Delivery status
    status = Column(String, default=WhatsAppMessageStatus.PENDING)
    error_message = Column(Text, nullable=True)
    
    # Auto-reply tracking
    is_auto_reply = Column(Boolean, default=False)
    auto_reply_rule_id = Column(Integer, ForeignKey("whatsapp_auto_replies.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", backref="whatsapp_messages")
    contact = relationship("WhatsAppContact", back_populates="messages")
    auto_reply_rule = relationship("WhatsAppAutoReply", backref="triggered_messages")
    
    __table_args__ = (
        Index("ix_whatsapp_messages_user_created", "user_id", "created_at"),
    )


class WhatsAppAutoReply(Base):
    """Auto-reply rules for WhatsApp automation."""
    __tablename__ = "whatsapp_auto_replies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Rule identification
    name = Column(String, nullable=False)  # "Welcome Message", "Price List", etc.
    description = Column(Text, nullable=True)
    
    # Trigger configuration
    trigger_type = Column(String, nullable=False)  # first_message, keyword, business_hours, all
    trigger_value = Column(String, nullable=True)  # For keyword: "hi|hello|hey", for hours: JSON
    
    # Response configuration
    response_type = Column(String, default="text")  # text, template, ai
    response_content = Column(Text, nullable=True)  # The message or template name
    response_template_params = Column(JSON, nullable=True)  # Template parameters
    
    # AI configuration (if response_type = "ai")
    ai_context = Column(Text, nullable=True)  # Additional context for AI
    ai_max_tokens = Column(Integer, default=150)
    
    # Rule settings
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Higher = checked first
    
    # Usage tracking
    times_triggered = Column(Integer, default=0)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", backref="whatsapp_auto_replies")
    
    __table_args__ = (
        Index("ix_whatsapp_auto_replies_user_active", "user_id", "is_active"),
    )


class WhatsAppBusinessProfile(Base):
    """Business profile for WhatsApp AI chatbot context."""
    __tablename__ = "whatsapp_business_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Business info
    business_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    industry = Column(String, nullable=True)
    
    # Products/Services (for AI context)
    products = Column(JSON, nullable=True)  # [{"name": "...", "price": 100, "description": "..."}]
    services = Column(JSON, nullable=True)
    
    # FAQs for AI to reference
    faqs = Column(JSON, nullable=True)  # [{"question": "...", "answer": "..."}]
    
    # Default messages
    greeting_message = Column(Text, nullable=True)  # First contact message
    away_message = Column(Text, nullable=True)  # Outside business hours
    
    # Business hours (JSON format)
    # {"monday": {"open": "08:00", "close": "18:00"}, "tuesday": {...}, ...}
    business_hours = Column(JSON, nullable=True)
    timezone = Column(String, default="Africa/Nairobi")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", backref="whatsapp_business_profile", uselist=False)


class WhatsAppBroadcastStatus(str, Enum):
    """Broadcast campaign status."""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WhatsAppTemplate(Base):
    """Cached WhatsApp message templates from Meta."""
    __tablename__ = "whatsapp_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Template info from Meta
    template_id = Column(String, nullable=False)  # Meta's template ID
    name = Column(String, nullable=False)
    language = Column(String, default="en")
    category = Column(String, nullable=True)  # MARKETING, UTILITY, AUTHENTICATION
    status = Column(String, nullable=True)  # APPROVED, PENDING, REJECTED
    
    # Template content
    components = Column(JSON, nullable=True)  # Header, body, footer, buttons
    
    # Usage tracking
    times_used = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    synced_at = Column(DateTime(timezone=True), nullable=True)  # Last sync from Meta
    
    # Relationships
    user = relationship("User", backref="whatsapp_templates")
    
    __table_args__ = (
        UniqueConstraint("user_id", "template_id", name="uq_user_template"),
        Index("ix_whatsapp_templates_user_name", "user_id", "name"),
    )


class WhatsAppBroadcast(Base):
    """Bulk message broadcast campaigns."""
    __tablename__ = "whatsapp_broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Campaign info
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # Message content
    message_type = Column(String, default="template")  # template, text
    template_id = Column(Integer, ForeignKey("whatsapp_templates.id"), nullable=True)
    template_variables = Column(JSON, nullable=True)  # Variables to replace in template
    text_content = Column(Text, nullable=True)  # For plain text broadcasts
    
    # Targeting
    target_type = Column(String, default="all")  # all, tag, selected
    target_tag = Column(String, nullable=True)  # For tag-based targeting
    target_contact_ids = Column(JSON, nullable=True)  # List of contact IDs
    
    # Scheduling
    status = Column(SQLEnum(WhatsAppBroadcastStatus), default=WhatsAppBroadcastStatus.DRAFT)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Statistics
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", backref="whatsapp_broadcasts")
    template = relationship("WhatsAppTemplate", backref="broadcasts")
    
    __table_args__ = (
        Index("ix_whatsapp_broadcasts_user_status", "user_id", "status"),
        Index("ix_whatsapp_broadcasts_scheduled", "status", "scheduled_at"),
    )


class WhatsAppBroadcastRecipient(Base):
    """Individual recipient status in a broadcast."""
    __tablename__ = "whatsapp_broadcast_recipients"

    id = Column(Integer, primary_key=True, index=True)
    broadcast_id = Column(Integer, ForeignKey("whatsapp_broadcasts.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    
    # Status tracking
    status = Column(String, default="pending")  # pending, sent, delivered, read, failed
    whatsapp_message_id = Column(String, nullable=True)  # From WhatsApp API
    error_message = Column(Text, nullable=True)
    
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    broadcast = relationship("WhatsAppBroadcast", backref="recipients")
    contact = relationship("WhatsAppContact", backref="broadcast_messages")
    
    __table_args__ = (
        UniqueConstraint("broadcast_id", "contact_id", name="uq_broadcast_contact"),
        Index("ix_broadcast_recipients_status", "broadcast_id", "status"),
    )


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

class TikTokProfile(Base):
    """TikTok creator profile."""
    __tablename__ = "tiktok_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    tiktok_user_id = Column(String, index=True)  # OpenID
    username = Column(String, index=True)
    display_name = Column(String)
    avatar_url = Column(String, nullable=True)
    follower_count = Column(Integer, default=0)
    following_count = Column(Integer, default=0)
    likes_count = Column(Integer, default=0)
    video_count = Column(Integer, default=0)
    accessToken = Column(String)  # Encrypted in production
    refreshToken = Column(String)
    is_active = Column(Boolean, default=True)
    
    # Monetization - Wallet System
    wallet_balance = Column(Numeric(10, 2), default=0.0)  # KES balance from premium link sales
    mpesa_withdrawal_number = Column(String, nullable=True)  # M-Pesa number for payouts
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="tiktok_profile")
    videos = relationship("TikTokVideo", back_populates="profile", cascade="all, delete-orphan")


class TikTokVideo(Base):
    """TikTok video content (posted or scheduled)."""
    __tablename__ = "tiktok_videos"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("tiktok_profiles.id"), index=True)
    tiktok_video_id = Column(String, nullable=True) # ID returned by TikTok API, e.g. "v_pub_file~..."
    
    # Content
    caption = Column(String)
    video_url = Column(String) # Path to local file or URL
    cover_image_url = Column(String, nullable=True)
    privacy_level = Column(String, default="SELF_ONLY") # SELF_ONLY, FRIENDS_MANAGER, PUBLIC_TO_EVERYONE
    
    # Status
    status = Column(String, default="draft") # draft, scheduled, published, failed
    scheduled_for = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    
    # Metrics (Viral Stats)
    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0)
    viral_score = Column(Float, default=0.0)  # Calculated metric
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    profile = relationship("TikTokProfile", back_populates="videos")


class PremiumLink(Base):
    """Paywalled links for Link-in-Bio."""
    __tablename__ = "premium_links"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("tiktok_profiles.id"), index=True)
    
    title = Column(String, nullable=False)
    url = Column(String, nullable=False) # The content URL (hidden until paid)
    price = Column(Numeric(10, 2), default=0.0) # KES
    description = Column(String, nullable=True)
    
    is_active = Column(Boolean, default=True)
    total_sales = Column(Integer, default=0)
    total_revenue = Column(Numeric(10, 2), default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    profile = relationship("TikTokProfile", backref="premium_links")


class CreatorTransaction(Base):
    """Track transactions from premium link sales (revenue split ledger)."""
    __tablename__ = "creator_transactions"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("tiktok_profiles.id"), index=True)
    premium_link_id = Column(Integer, ForeignKey("premium_links.id"), nullable=True, index=True)
    
    # Payment details
    paystack_reference = Column(String, unique=True, nullable=True, index=True)
    fan_email = Column(String, nullable=True)
    fan_phone = Column(String, nullable=True)
    
    # Amounts in KES
    gross_amount = Column(Numeric(10, 2), nullable=False)  # Total paid by fan
    platform_fee = Column(Numeric(10, 2), nullable=False)  # Arrotech's cut (e.g., 10%)
    creator_amount = Column(Numeric(10, 2), nullable=False)  # Creator's share (e.g., 90%)
    paystack_fee = Column(Numeric(10, 2), default=0.0)  # Paystack's cut (for reference)
    
    # Status
    status = Column(String, default="pending")  # pending, completed, failed, refunded
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    profile = relationship("TikTokProfile", backref="transactions")
    premium_link = relationship("PremiumLink", backref="transactions")


class TipTransaction(Base):
    """Tip/donation transactions from fans to creators."""
    __tablename__ = "tip_transactions"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("tiktok_profiles.id"), index=True)
    
    # Fan info
    fan_email = Column(String, nullable=True)
    fan_name = Column(String, nullable=True)
    fan_message = Column(Text, nullable=True)  # Optional message with tip
    
    # Payment details
    paystack_reference = Column(String, unique=True, nullable=True, index=True)
    amount = Column(Numeric(10, 2), nullable=False)  # KES
    platform_fee = Column(Numeric(10, 2), nullable=False)  # Arrotech's cut
    creator_amount = Column(Numeric(10, 2), nullable=False)  # Creator's share
    
    # Status
    status = Column(String, default="pending")  # pending, completed, failed
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    profile = relationship("TikTokProfile", backref="tips")


class LinkClickAnalytics(Base):
    """Track clicks and views on premium links for analytics."""
    __tablename__ = "link_click_analytics"

    id = Column(Integer, primary_key=True, index=True)
    premium_link_id = Column(Integer, ForeignKey("premium_links.id"), index=True)
    
    # Event type
    event_type = Column(String, nullable=False)  # "view", "click", "purchase"
    
    # Source tracking
    referrer = Column(String, nullable=True)  # Where the click came from
    source = Column(String, nullable=True)  # tiktok, whatsapp, instagram, other
    user_agent = Column(String, nullable=True)
    ip_hash = Column(String, nullable=True)  # Hashed for privacy
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Index for efficient queries
    __table_args__ = (
        Index('ix_link_analytics_date', 'premium_link_id', 'created_at'),
    )
    
    # Relationships
    premium_link = relationship("PremiumLink", backref="analytics")


class FanContact(Base):
    """Collected fan contacts from purchases and tips."""
    __tablename__ = "fan_contacts"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("tiktok_profiles.id"), index=True)
    
    # Contact info
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    name = Column(String, nullable=True)
    
    # Source tracking
    source_type = Column(String, nullable=False)  # "premium_link", "tip", "subscription"
    source_link_id = Column(Integer, ForeignKey("premium_links.id"), nullable=True)
    
    # Engagement stats
    total_spent = Column(Numeric(10, 2), default=0.0)  # Total KES spent
    purchase_count = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Unique constraint: one email per creator
    __table_args__ = (
        UniqueConstraint('profile_id', 'email', name='uq_fan_creator_email'),
    )
    
    # Relationships
    profile = relationship("TikTokProfile", backref="fans")
    source_link = relationship("PremiumLink", backref="fan_contacts")


class BlogCategory(Base):
    """Blog category model."""
    __tablename__ = "blog_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    color = Column(String, nullable=True)
    post_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    posts = relationship("BlogPostModel", back_populates="category")


class BlogPostModel(Base):
    """Blog post model for company blog."""
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    cover_image = Column(String, nullable=True)
    author_name = Column(String, nullable=False)
    author_avatar = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("blog_categories.id"), nullable=True)
    tags = Column(JSON, nullable=True)
    status = Column(String, default="draft")  # draft, published, archived
    is_featured = Column(Boolean, default=False)
    read_time = Column(String, nullable=True)
    views_count = Column(Integer, default=0)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    category = relationship("BlogCategory", back_populates="posts")


# ============================================================================
# Organization Models - Multi-tenant B2B organization onboarding
# ============================================================================


class Organization(Base):
    """Organization model for company/team onboarding."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    logo_url = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    website = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    company_size = Column(String, nullable=True)  # 1-10, 11-50, 51-200, 201-500, 500+
    billing_email = Column(String, nullable=True)
    subscription_tier = Column(String, default=SubscriptionTier.FREE)
    settings = Column(JSON, nullable=True)  # Org-level settings and config
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("OrganizationInvitation", back_populates="organization", cascade="all, delete-orphan")
    departments = relationship("Department", back_populates="organization", cascade="all, delete-orphan")
    audit_log_entries = relationship("AuditLogEntry", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    """Membership link between users and organizations."""
    __tablename__ = "organization_members"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, default=OrgRole.MEMBER, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=True)  # e.g. "Engineering Lead"
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_org_role", "org_id", "role"),
    )

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="organization_memberships")
    department = relationship("Department", back_populates="members")


class OrganizationInvitation(Base):
    """Pending invitations to join an organization."""
    __tablename__ = "organization_invitations"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, nullable=False)
    role = Column(String, default=OrgRole.MEMBER, nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default=OrgInvitationStatus.PENDING, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_org_invitations_email_status", "email", "status"),
    )

    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[invited_by])


class Department(Base):
    """Departments within an organization."""
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    head_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_department_name"),
    )

    # Relationships
    organization = relationship("Organization", back_populates="departments")
    head = relationship("User", foreign_keys=[head_id])
    members = relationship("OrganizationMember", back_populates="department")


class AuditLogEntry(Base):
    """Immutable audit log for organization actions."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)  # e.g. "member.added", "org.updated"
    entity_type = Column(String, nullable=True)  # e.g. "member", "department"
    entity_id = Column(String, nullable=True)  # ID of affected entity
    details = Column(JSON, nullable=True)  # Additional context
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_log_org_created", "org_id", "created_at"),
        Index("ix_audit_log_action", "org_id", "action"),
    )

    # Relationships
    organization = relationship("Organization", back_populates="audit_log_entries")
    actor = relationship("User", foreign_keys=[actor_id])
