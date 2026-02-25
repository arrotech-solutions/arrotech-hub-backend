
"""initial_migration

Revision ID: 001
Revises: 
Create Date: 2026-01-08
"""
from alembic import op
import sqlalchemy as sa
from src.database import Base

# Import all models to ensure they are registered with Base.metadata
from src.models import (
    User, Subscription, UsageLog, Connection, UserSettings, 
    Conversation, Message, Workflow, WorkflowStep, WorkflowExecution,
    WorkflowStepExecution, WorkflowDownload, WorkflowReview, 
    Payment, CreatorProfile, WorkflowVersion, WorkflowAnalytics,
    Notification, WorkflowFavorite, UserPreferences, CreatorFollower,
    ActivityFeedItem, MpesaPayment, MpesaAgentConfig, UsageRecord,
    Invoice, FraudSignal, AccessRequest, WhatsAppContact, WhatsAppMessage,
    WhatsAppAutoReply, WhatsAppBusinessProfile, WhatsAppTemplate,
    WhatsAppBroadcast, WhatsAppBroadcastRecipient, TikTokProfile,
    TikTokVideo, PremiumLink, CreatorTransaction, TipTransaction,
    LinkClickAnalytics, FanContact, BlogCategory, BlogPostModel,
    WebAuthnCredential
)

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Use the metadata from our models to create everything at once
    # This is a robust way to "consolidate" a reset database
    bind = op.get_bind()
    Base.metadata.create_all(bind)

def downgrade():
    # Drop everything if we need to roll back point zero
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
