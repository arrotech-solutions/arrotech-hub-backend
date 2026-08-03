"""
GDPR/CCPA account erasure helpers.

Bulk `DELETE FROM` bypasses ORM relationship cascades, so children must be
removed (or FKs nulled) in dependency order before deleting the user row.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ActivityFeedItem,
    AppToken,
    AuthorizationCode,
    Connection,
    Conversation,
    CreatorFollower,
    CreatorProfile,
    CreatorTransaction,
    DataSource,
    Department,
    DeveloperApp,
    FanContact,
    FraudSignal,
    Invoice,
    KnowledgeBase,
    LinkClickAnalytics,
    Message,
    MessagingConversation,
    MpesaAgentConfig,
    MpesaPayment,
    Notification,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Payment,
    PremiumLink,
    ProcessedWebhookMessage,
    StkOrderMapping,
    StkPaymentAttempt,
    Subscription,
    SyncLog,
    TipTransaction,
    TikTokProfile,
    TikTokVideo,
    ToolAuditLog,
    ToolProposal,
    UsageLog,
    UsageRecord,
    User,
    UserPreferences,
    UserSettings,
    WebAuthnCredential,
    WhatsAppAutoReply,
    WhatsAppBroadcast,
    WhatsAppBroadcastRecipient,
    WhatsAppBusinessProfile,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppQuickReply,
    WhatsAppTemplate,
    Workflow,
    WorkflowAnalytics,
    WorkflowDownload,
    WorkflowExecution,
    WorkflowFavorite,
    WorkflowReview,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowVersion,
)

logger = logging.getLogger(__name__)


async def erase_user_account(db: AsyncSession, user: User) -> None:
    """Permanently delete a user and dependent rows. Caller commits."""
    uid: UUID = user.id

    # ── Conversations / messages ─────────────────────────────────────────
    conv_ids = select(Conversation.id).where(Conversation.user_id == uid)
    await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
    await db.execute(delete(Conversation).where(Conversation.user_id == uid))

    # ── Workflows (children before parent; bulk delete skips ORM cascades) ─
    wf_ids = select(Workflow.id).where(Workflow.user_id == uid)
    exec_ids = select(WorkflowExecution.id).where(
        (WorkflowExecution.user_id == uid) | (WorkflowExecution.workflow_id.in_(wf_ids))
    )
    step_ids = select(WorkflowStep.id).where(WorkflowStep.workflow_id.in_(wf_ids))

    await db.execute(
        delete(WorkflowStepExecution).where(
            (WorkflowStepExecution.workflow_execution_id.in_(exec_ids))
            | (WorkflowStepExecution.step_id.in_(step_ids))
        )
    )
    await db.execute(delete(WorkflowExecution).where(WorkflowExecution.id.in_(exec_ids)))
    await db.execute(delete(WorkflowStep).where(WorkflowStep.workflow_id.in_(wf_ids)))
    await db.execute(delete(WorkflowVersion).where(WorkflowVersion.workflow_id.in_(wf_ids)))
    # Versions on other users' workflows that this user authored
    await db.execute(
        update(WorkflowVersion)
        .where(WorkflowVersion.created_by == uid)
        .values(created_by=None)
    )
    await db.execute(delete(WorkflowAnalytics).where(WorkflowAnalytics.workflow_id.in_(wf_ids)))
    await db.execute(
        delete(WorkflowDownload).where(
            (WorkflowDownload.user_id == uid) | (WorkflowDownload.workflow_id.in_(wf_ids))
        )
    )
    await db.execute(
        delete(WorkflowReview).where(
            (WorkflowReview.user_id == uid) | (WorkflowReview.workflow_id.in_(wf_ids))
        )
    )
    await db.execute(
        delete(WorkflowFavorite).where(
            (WorkflowFavorite.user_id == uid) | (WorkflowFavorite.workflow_id.in_(wf_ids))
        )
    )
    await db.execute(
        update(Notification)
        .where(Notification.workflow_id.in_(wf_ids))
        .values(workflow_id=None)
    )
    await db.execute(
        update(ActivityFeedItem)
        .where(ActivityFeedItem.workflow_id.in_(wf_ids))
        .values(workflow_id=None)
    )
    await db.execute(delete(Workflow).where(Workflow.user_id == uid))

    # ── Notifications / activity / social graph ──────────────────────────
    await db.execute(
        update(Notification).where(Notification.actor_id == uid).values(actor_id=None)
    )
    await db.execute(delete(Notification).where(Notification.user_id == uid))
    await db.execute(
        delete(ActivityFeedItem).where(
            (ActivityFeedItem.user_id == uid) | (ActivityFeedItem.actor_id == uid)
        )
    )
    await db.execute(
        delete(CreatorFollower).where(
            (CreatorFollower.follower_id == uid) | (CreatorFollower.following_id == uid)
        )
    )
    await db.execute(delete(UserPreferences).where(UserPreferences.user_id == uid))

    # ── Usage / billing ─────────────────────────────────────────────────
    await db.execute(delete(UsageLog).where(UsageLog.user_id == uid))
    await db.execute(delete(UsageRecord).where(UsageRecord.user_id == uid))
    await db.execute(delete(Subscription).where(Subscription.user_id == uid))
    await db.execute(delete(Payment).where(Payment.user_id == uid))
    await db.execute(delete(Invoice).where(Invoice.user_id == uid))
    await db.execute(
        update(MpesaPayment).where(MpesaPayment.locked_by == uid).values(locked_by=None)
    )
    await db.execute(delete(MpesaPayment).where(MpesaPayment.user_id == uid))
    await db.execute(delete(StkPaymentAttempt).where(StkPaymentAttempt.user_id == uid))
    await db.execute(delete(StkOrderMapping).where(StkOrderMapping.user_id == uid))
    await db.execute(delete(MpesaAgentConfig).where(MpesaAgentConfig.user_id == uid))
    await db.execute(
        update(FraudSignal).where(FraudSignal.reviewed_by == uid).values(reviewed_by=None)
    )
    await db.execute(delete(FraudSignal).where(FraudSignal.user_id == uid))

    # ── Connections / settings / security ────────────────────────────────
    await db.execute(delete(Connection).where(Connection.user_id == uid))
    await db.execute(delete(UserSettings).where(UserSettings.user_id == uid))
    await db.execute(delete(WebAuthnCredential).where(WebAuthnCredential.user_id == uid))
    await db.execute(delete(ToolAuditLog).where(ToolAuditLog.user_id == uid))
    await db.execute(delete(ToolProposal).where(ToolProposal.user_id == uid))
    await db.execute(
        delete(ProcessedWebhookMessage).where(ProcessedWebhookMessage.user_id == uid)
    )

    # ── WhatsApp ─────────────────────────────────────────────────────────
    contact_ids = select(WhatsAppContact.id).where(WhatsAppContact.user_id == uid)
    broadcast_ids = select(WhatsAppBroadcast.id).where(WhatsAppBroadcast.user_id == uid)

    await db.execute(
        delete(WhatsAppBroadcastRecipient).where(
            (WhatsAppBroadcastRecipient.broadcast_id.in_(broadcast_ids))
            | (WhatsAppBroadcastRecipient.contact_id.in_(contact_ids))
        )
    )
    await db.execute(delete(WhatsAppBroadcast).where(WhatsAppBroadcast.user_id == uid))
    await db.execute(delete(WhatsAppMessage).where(WhatsAppMessage.user_id == uid))
    await db.execute(
        update(WhatsAppContact)
        .where(WhatsAppContact.assigned_to_id == uid)
        .values(assigned_to_id=None)
    )
    await db.execute(delete(WhatsAppContact).where(WhatsAppContact.user_id == uid))
    await db.execute(delete(WhatsAppAutoReply).where(WhatsAppAutoReply.user_id == uid))
    await db.execute(delete(WhatsAppTemplate).where(WhatsAppTemplate.user_id == uid))
    await db.execute(delete(WhatsAppQuickReply).where(WhatsAppQuickReply.user_id == uid))
    await db.execute(
        delete(WhatsAppBusinessProfile).where(WhatsAppBusinessProfile.user_id == uid)
    )

    # ── TikTok / creator economy ─────────────────────────────────────────
    profile_ids = select(TikTokProfile.id).where(TikTokProfile.user_id == uid)
    link_ids = select(PremiumLink.id).where(PremiumLink.profile_id.in_(profile_ids))
    await db.execute(delete(LinkClickAnalytics).where(LinkClickAnalytics.premium_link_id.in_(link_ids)))
    await db.execute(delete(CreatorTransaction).where(CreatorTransaction.profile_id.in_(profile_ids)))
    await db.execute(delete(TipTransaction).where(TipTransaction.profile_id.in_(profile_ids)))
    await db.execute(delete(FanContact).where(FanContact.profile_id.in_(profile_ids)))
    await db.execute(delete(PremiumLink).where(PremiumLink.profile_id.in_(profile_ids)))
    await db.execute(delete(TikTokVideo).where(TikTokVideo.profile_id.in_(profile_ids)))
    await db.execute(delete(TikTokProfile).where(TikTokProfile.user_id == uid))
    await db.execute(delete(CreatorProfile).where(CreatorProfile.user_id == uid))

    # ── Messaging CCM ────────────────────────────────────────────────────
    await db.execute(
        delete(MessagingConversation).where(MessagingConversation.owner_user_id == uid)
    )

    # ── RAG / knowledge bases ────────────────────────────────────────────
    kb_ids = select(KnowledgeBase.id).where(KnowledgeBase.user_id == uid)
    ds_ids = select(DataSource.id).where(DataSource.kb_id.in_(kb_ids))
    await db.execute(delete(SyncLog).where(SyncLog.data_source_id.in_(ds_ids)))
    await db.execute(delete(DataSource).where(DataSource.kb_id.in_(kb_ids)))
    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.user_id == uid))

    # ── Developer apps ───────────────────────────────────────────────────
    app_ids = select(DeveloperApp.id).where(DeveloperApp.user_id == uid)
    await db.execute(delete(AppToken).where(AppToken.app_id.in_(app_ids)))
    await db.execute(delete(AuthorizationCode).where(AuthorizationCode.app_id.in_(app_ids)))
    # AppToken / AuthorizationCode may also reference user_id directly
    await db.execute(delete(AppToken).where(AppToken.user_id == uid))
    await db.execute(delete(AuthorizationCode).where(AuthorizationCode.user_id == uid))
    await db.execute(delete(DeveloperApp).where(DeveloperApp.user_id == uid))

    # ── Organizations ────────────────────────────────────────────────────
    await db.execute(
        update(Department).where(Department.head_id == uid).values(head_id=None)
    )
    await db.execute(
        delete(OrganizationInvitation).where(OrganizationInvitation.invited_by == uid)
    )

    # Orgs solely owned by this user → delete; otherwise reassign created_by
    owned_orgs = (
        await db.execute(select(Organization).where(Organization.created_by == uid))
    ).scalars().all()
    for org in owned_orgs:
        other = (
            await db.execute(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.org_id == org.id,
                    OrganizationMember.user_id != uid,
                    OrganizationMember.is_active == True,  # noqa: E712
                ).limit(1)
            )
        ).scalar_one_or_none()
        if other:
            org.created_by = other
        else:
            await db.delete(org)

    await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == uid))

    # ── User row ─────────────────────────────────────────────────────────
    await db.delete(user)
    logger.info("Erased account data for user_id=%s", uid)
