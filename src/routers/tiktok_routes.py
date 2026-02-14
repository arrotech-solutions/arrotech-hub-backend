from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
import logging
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
from typing import Optional, List

from ..database import get_db
from ..models import Connection, ConnectionStatus, User, TikTokProfile, TikTokVideo, PremiumLink
from ..config import settings
from ..routers.auth_router import get_current_user

router = APIRouter(
    prefix="/api/tiktok",
    tags=["tiktok"]
)

logger = logging.getLogger(__name__)

# Constants
TIKTOK_API_URL = "https://open.tiktokapis.com/v2"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate TikTok OAuth URL (Login Kit)."""
    
    if not settings.TIKTOK_CLIENT_KEY or not settings.TIKTOK_CLIENT_SECRET:
         # Fallback for dev if not set
         logger.warning("TikTok credentials missing in env")
    
    # Scopes needed for Login Kit + Video Publishing
    # user.info.basic, user.info.stats, user.info.profile, video.publish, video.upload
    scopes = "user.info.basic,user.info.stats,user.info.profile,video.publish,video.upload"
    
    redirect_uri = f"{settings.API_BASE_URL}/api/tiktok/callback"
    
    # DEBUG: Print to console to verify mismatch
    logger.info(f"TIKTOK DEBUG: Client Key={settings.TIKTOK_CLIENT_KEY}")
    logger.info(f"TIKTOK DEBUG: Redirect URI={redirect_uri}")
    logger.info(f"TIKTOK DEBUG: API Base URL={settings.API_BASE_URL}")
    
    # State includes user_id to link connection
    state = str(user.id)
    
    # CSRF Token should logically be used here too, but simple state for now
    
    params = {
        "client_key": settings.TIKTOK_CLIENT_KEY,
        "scope": scopes,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state
    }
    
    auth_url = f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"
    
    # DEBUG: Print full URL to check for encoding issues
    logger.info(f"TIKTOK DEBUG: FULL AUTH URL={auth_url}")
    
    return {"url": auth_url}

from ..services.tiktok_service import TikTokService

@router.get("/callback")
async def oauth_callback(
    code: str, 
    state: str, 
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle TikTok OAuth callback."""
    if error:
        logger.error(f"TikTok OAuth error: {error} - {error_description}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}"
        )

    service = TikTokService(db)
    try:
        user_id = int(state)
        redirect_uri = f"{settings.API_BASE_URL}/api/tiktok/callback"
        
        # 1. Exchange Code
        auth_data = await service.exchange_code_for_token(code, redirect_uri)
        
        # 2. Sync Profile
        await service.sync_profile(user_id, auth_data)
        
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/tiktok?success=connected"
        )
    except Exception as e:
        logger.error(f"Error in TikTok callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )
    finally:
        await service.close()

@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get connected TikTok profile."""
    # Check for linked profile
    stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    
    if not profile:
        return {"connected": False}
        
    # Calculate stats from local DB (TikTokVideo table)
    from ..models import TikTokVideo
    
    # Scheduled posts count
    scheduled_stmt = select(func.count(TikTokVideo.id)).filter(
        TikTokVideo.profile_id == profile.id,
        TikTokVideo.status == "scheduled"
    )
    scheduled_result = await db.execute(scheduled_stmt)
    scheduled_count = scheduled_result.scalar() or 0
    
    # Total Views (sum of all video views)
    views_stmt = select(func.sum(TikTokVideo.view_count)).filter(
        TikTokVideo.profile_id == profile.id
    )
    views_result = await db.execute(views_stmt)
    total_views = views_result.scalar() or 0
    
    # Engagement Rate (Likes + Comments + Shares / Views * 100) - simplified
    # First get total engagement actions
    engagement_stmt = select(
        func.sum(TikTokVideo.like_count),
        func.sum(TikTokVideo.comment_count),
        func.sum(TikTokVideo.share_count)
    ).filter(TikTokVideo.profile_id == profile.id)
    
    eng_result = await db.execute(engagement_stmt)
    likes, comments, shares = eng_result.one()
    
    total_actions = (likes or 0) + (comments or 0) + (shares or 0)
    engagement_rate = 0.0
    if total_views > 0:
        engagement_rate = (total_actions / total_views) * 100
        
    return {
        "connected": True,
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "follower_count": profile.follower_count,
        "following_count": profile.following_count,
        "total_likes": profile.likes_count, 
        "video_count": profile.video_count,
        "profile_url": f"https://www.tiktok.com/@{profile.username}" if profile.username else None,
        "scheduled_posts": scheduled_count,
        "total_views": total_views, # Still calculated from synced videos for now
        "engagement_rate": f"{engagement_rate:.1f}%"
    }
        
from fastapi import File, UploadFile
from pydantic import BaseModel
from ..services.viral_engine import viral_engine
from ..services.file_management_service import file_management_service

# Models
class CaptionRequest(BaseModel):
    topic: str
    tone: str = "funny"
    context: Optional[str] = None

@router.post("/generate-caption")
async def generate_caption(
    request: CaptionRequest,
    user: User = Depends(get_current_user)
):
    """Generate a viral Sheng caption."""
    return await viral_engine.generate_sheng_caption(
        topic=request.topic,
        tone=request.tone,
        context=request.context
    )

@router.get("/scheduled-posts")
async def get_scheduled_posts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all scheduled posts for the current user."""
    from ..models import TikTokVideo # usage inside function to avoid circular imports if any, though previously imported at top
    
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        return []

    stmt = select(TikTokVideo).filter(
        TikTokVideo.profile_id == profile.id,
        TikTokVideo.status == 'scheduled'
    ).order_by(TikTokVideo.scheduled_for.asc())
    
    result = await db.execute(stmt)
    posts = result.scalars().all()
    
    return [
        {
            "id": post.id,
            "caption": post.caption,
            "scheduled_for": post.scheduled_for,
            "video_url": post.video_url
        }
        for post in posts
    ]

class ScheduleRequest(BaseModel):
    caption: str
    video_path: str
    scheduled_time: Optional[datetime] = None
    hashtags: List[str] = []
    tone: Optional[str] = "funny"
    privacy_level: Optional[str] = "SELF_ONLY"

@router.post("/schedule")
async def schedule_post(
    request: ScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Schedule a TikTok post."""
    # Find profile
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Please connect TikTok account first")

    # Create Video Record
    new_video = TikTokVideo(
        profile_id=profile.id,
        video_url=request.video_path,
        caption=request.caption,
        status="scheduled" if request.scheduled_time else "draft",
        scheduled_for=request.scheduled_time,
        privacy_level=request.privacy_level, # Save to DB
        created_at=datetime.utcnow()
    )
    
    # User model relationship might expect "user_id" on TikTokVideo if "owner" relationship exists.
    # The model definition I saw: "profile_id = ... ForeignKey...". 
    # I didn't see "user_id" column on TikTokVideo in the read lines (1200-1230).
    # Checking lines 1200+ again...
    # id, profile_id, tiktok_video_id, caption, video_url...
    # It does NOT have user_id. It relies on profile.
    
    db.add(new_video)
    await db.commit()
    await db.refresh(new_video)
    
    return {
        "success": True,
        "video_id": new_video.id,
        "status": new_video.status,
        "scheduled_for": new_video.scheduled_for
    }
@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """
    Upload a video file to the server (staging for TikTok).
    Returns file path and metadata.
    """
    # 1. Save locally using FileManagementService
    upload_result = await file_management_service.upload_file(file, user.id)
    
    if not upload_result.get("success"):
         raise HTTPException(status_code=500, detail=upload_result.get("error"))
         
    # 2. (Future) Trigger Viral Analysis here
    # analysis = await viral_engine.analyze_video_virality({...})
    
    return {
        "success": True,
        "message": "Video uploaded successfully",
        "file_path": upload_result.get("path"),
        "filename": upload_result.get("filename")
    }

from ..services.viral_card_generator import viral_card_generator

@router.get("/viral-card")
async def get_viral_card(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a shareable viral score card."""
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
        
    username = profile.display_name or profile.username or "User"
    views = "12.5K" # Placeholder until we sync real views from videos
    followers = str(profile.follower_count) if profile.follower_count else "0"
    
    result = viral_card_generator.generate_score_card(
        username=username,
        views=views,
        followers=followers
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to generate image")
        
    return result

@router.get("/public/u/{username}")
async def get_public_profile(
    username: str,
    db: AsyncSession = Depends(get_db)
):
    """Get public profile data for Link-in-Bio page."""
    # Find profile by username (case insensitive)
    stmt = select(TikTokProfile).filter(TikTokProfile.username.ilike(username))
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    # Get latest videos (limit 6)
    videos_stmt = select(TikTokVideo).filter(
        TikTokVideo.profile_id == profile.id,
        TikTokVideo.status == "published" # Only show published
    ).order_by(TikTokVideo.created_at.desc()).limit(6)
    
    videos_res = await db.execute(videos_stmt)
    videos = videos_res.scalars().all()
    

    # Get Premium Links
    links_stmt = select(PremiumLink).filter(
        PremiumLink.profile_id == profile.id,
        PremiumLink.is_active == True
    )
    links_res = await db.execute(links_stmt)
    premium_links = links_res.scalars().all()
    
    return {
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "follower_count": profile.follower_count,
        "bio": "Welcome to my official page! 🚀", 
        "links": [
            {
                "id": l.id,
                "title": l.title, 
                "price": l.price,
                "is_locked": True,
                "description": l.description
            } for l in premium_links
        ] + [
             {"title": "WhatsApp Me", "url": "#", "icon": "message-circle"},
             {"title": "Check my Store", "url": "#", "icon": "shopping-bag"}
        ],
        "videos": [
            {
                "id": v.id,
                "thumbnail_url": v.thumbnail_url or "https://via.placeholder.com/150",
                "caption": v.caption,
                "views": v.views_count
            } for v in videos
        ]
    }

class PremiumLinkRequest(BaseModel):
    title: str
    url: str
    price: float
    description: Optional[str] = None

@router.post("/premium-links")
async def create_premium_link(
    request: PremiumLinkRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a paywalled link."""
    stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
        
    link = PremiumLink(
        profile_id=profile.id,
        title=request.title,
        url=request.url,
        price=request.price,
        description=request.description
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {"success": True, "link_id": link.id}

@router.post("/premium-links/{link_id}/unlock")
async def unlock_premium_link(
    link_id: int,
    phone_number: str, # For M-Pesa STK Push
    db: AsyncSession = Depends(get_db)
):
    """
    Simulate M-Pesa STK Push to unlock content.
    In prod, this would trigger an async payment and wait for webhook.
    For demo, we autosuccess.
    """
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
        
    # Mock M-Pesa Payment Logic
    # await mpesa_service.stk_push(phone_number, link.price)
    
    # Record Sale (Mock)
    link.total_sales += 1
    link.total_revenue += link.price
    await db.commit()
    
    return {
        "success": True,
        "message": f"Payment of KES {link.price} received from {phone_number}",
        "unlocked_url": link.url 
    }


# ============================================================================
# New Premium Link Purchase Flow (Paystack)
# ============================================================================

from ..services.payment_service import PaymentService
from ..models import CreatorTransaction

class PurchaseRequest(BaseModel):
    email: str
    callback_url: Optional[str] = None

@router.post("/premium-links/{link_id}/purchase")
async def initiate_link_purchase(
    link_id: int,
    request: PurchaseRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate a Paystack transaction to purchase a premium link.
    Returns authorization_url to redirect user to Paystack checkout.
    """
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    if not link.is_active:
        raise HTTPException(status_code=400, detail="This link is no longer available")
    
    # Get creator profile for metadata
    profile = await db.get(TikTokProfile, link.profile_id)
    
    payment_service = PaymentService()
    
    result = await payment_service.initialize_paystack_transaction(
        email=request.email,
        amount_kes=float(link.price),
        metadata={
            "type": "premium_link_purchase",
            "link_id": link_id,
            "link_title": link.title,
            "creator_profile_id": link.profile_id,
            "creator_username": profile.username if profile else None
        },
        callback_url=request.callback_url
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Payment initialization failed"))
    
    return {
        "success": True,
        "authorization_url": result.get("authorization_url"),
        "reference": result.get("reference"),
        "amount": float(link.price),
        "link_title": link.title
    }


@router.get("/premium-links/verify")
async def verify_link_purchase(
    reference: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Verify a Paystack payment and unlock the premium link content.
    Called after user returns from Paystack checkout.
    """
    payment_service = PaymentService()
    
    # Verify with Paystack
    result = await payment_service.verify_paystack_payment(reference)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Payment verification failed"))
    
    # Payment verified - now process the unlock
    # The metadata contains link_id
    # Note: In a real webhook scenario, this would be triggered by Paystack webhook
    
    # For now, parse metadata from the verification result
    # This is a simplified flow - production should use webhooks
    
    return {
        "success": True,
        "status": "completed",
        "message": "Payment verified successfully",
        "reference": reference
    }


class VerifyAndUnlockRequest(BaseModel):
    reference: str

@router.post("/premium-links/{link_id}/verify-and-unlock")
async def verify_and_unlock_content(
    link_id: int,
    request: VerifyAndUnlockRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Verify payment and return the unlocked content URL.
    Also updates creator wallet balance.
    """
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    payment_service = PaymentService()
    
    # Verify with Paystack
    result = await payment_service.verify_paystack_payment(request.reference)
    
    if not result.get("success") or result.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Payment not verified")
    
    # Check if we already processed this transaction
    existing_txn = await db.execute(
        select(CreatorTransaction).filter(CreatorTransaction.paystack_reference == request.reference)
    )
    if existing_txn.scalar_one_or_none():
        # Already processed - just return the URL
        return {
            "success": True,
            "unlocked_url": link.url,
            "message": "Content already unlocked"
        }
    
    # Calculate revenue split
    split = payment_service.calculate_revenue_split(float(link.price))
    
    # Create transaction record
    transaction = CreatorTransaction(
        profile_id=link.profile_id,
        premium_link_id=link_id,
        paystack_reference=request.reference,
        fan_email=result.get("customer_email"),
        gross_amount=split["gross_amount"],
        platform_fee=split["platform_fee"],
        creator_amount=split["creator_amount"],
        status="completed"
    )
    db.add(transaction)
    
    # Update link stats
    link.total_sales += 1
    link.total_revenue += link.price
    
    # Update creator wallet balance
    profile = await db.get(TikTokProfile, link.profile_id)
    if profile:
        from decimal import Decimal
        current_balance = profile.wallet_balance or Decimal("0.0")
        profile.wallet_balance = current_balance + Decimal(str(split["creator_amount"]))
    
    # Save fan contact for CRM
    fan_email = result.get("customer_email")
    if fan_email and profile:
        await _save_fan_contact(
            db,
            profile.id,
            fan_email,
            None,  # name
            None,  # phone
            "premium_link",
            link_id,
            float(link.price)
        )
    
    await db.commit()
    
    return {
        "success": True,
        "unlocked_url": link.url,
        "message": f"Content unlocked! Creator earned KES {split['creator_amount']}"
    }



# ============================================================================
# Creator Wallet & Monetization Endpoints
# ============================================================================

@router.get("/wallet")
async def get_wallet_info(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get creator wallet balance and transaction summary."""
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
    
    # Get recent transactions
    txn_stmt = select(CreatorTransaction).filter(
        CreatorTransaction.profile_id == profile.id,
        CreatorTransaction.status == "completed"
    ).order_by(CreatorTransaction.created_at.desc()).limit(10)
    
    txn_result = await db.execute(txn_stmt)
    transactions = txn_result.scalars().all()
    
    # Calculate totals
    total_earned_stmt = select(func.sum(CreatorTransaction.creator_amount)).filter(
        CreatorTransaction.profile_id == profile.id,
        CreatorTransaction.status == "completed"
    )
    total_earned_res = await db.execute(total_earned_stmt)
    total_earned = total_earned_res.scalar() or 0
    
    return {
        "wallet_balance": float(profile.wallet_balance or 0),
        "total_earned": float(total_earned),
        "mpesa_withdrawal_number": profile.mpesa_withdrawal_number,
        "recent_transactions": [
            {
                "id": t.id,
                "amount": float(t.creator_amount),
                "gross": float(t.gross_amount),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "fan_email": t.fan_email
            } for t in transactions
        ]
    }


class SetWithdrawalNumberRequest(BaseModel):
    mpesa_number: str

@router.post("/wallet/set-withdrawal-number")
async def set_withdrawal_number(
    request: SetWithdrawalNumberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Set the M-Pesa number for withdrawals."""
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
    
    profile.mpesa_withdrawal_number = request.mpesa_number
    await db.commit()
    
    return {"success": True, "message": "Withdrawal number updated"}


class WithdrawRequest(BaseModel):
    mpesa_number: str
    amount: Optional[float] = None  # If None, withdraw full balance

@router.post("/wallet/withdraw")
async def withdraw_to_mpesa(
    request: WithdrawRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Withdraw wallet balance to M-Pesa number via Paystack Transfers.
    """
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
    
    # Get current balance
    current_balance = float(profile.wallet_balance or 0)
    
    if current_balance <= 0:
        raise HTTPException(status_code=400, detail="No funds available for withdrawal")
    
    # Determine withdrawal amount
    withdraw_amount = request.amount if request.amount else current_balance
    
    if withdraw_amount > current_balance:
        raise HTTPException(status_code=400, detail=f"Insufficient balance. Available: KES {current_balance}")
    
    # Minimum withdrawal check
    if withdraw_amount < 10:
        raise HTTPException(status_code=400, detail="Minimum withdrawal is KES 10")
    
    # Save the M-Pesa number
    profile.mpesa_withdrawal_number = request.mpesa_number
    
    payment_service = PaymentService()
    
    # Step 1: Create transfer recipient
    recipient_result = await payment_service.create_paystack_transfer_recipient(
        name=profile.display_name or user.name or "Creator",
        phone_number=request.mpesa_number
    )
    
    if not recipient_result.get("success"):
        raise HTTPException(status_code=500, detail=recipient_result.get("error", "Failed to create payment recipient"))
    
    recipient_code = recipient_result.get("recipient_code")
    
    # Step 2: Initiate transfer
    transfer_result = await payment_service.initiate_paystack_transfer(
        amount_kes=withdraw_amount,
        recipient_code=recipient_code,
        reason=f"Arrotech Hub Withdrawal - {profile.username}"
    )
    
    # Handle transfer result - check for status
    is_pending = False
    
    # Paystack Transfer Statuses: success, pending, otp, failed
    # If status is "success", it might still be queued. 
    # If "pending" or "otp", it definitely needs waiting.
    
    transfer_status = transfer_result.get("status")
    
    if not transfer_result.get("success"):
        # API call failed completely
        error_msg = transfer_result.get("error", "")
        # If it's the starter business error, treat as pending withdrawal (manual processing)
        if "starter business" in error_msg.lower() or "third party payouts" in error_msg.lower():
            is_pending = True
            logger.info(f"[WITHDRAWAL] Pending due to account tier: {error_msg}")
        else:
            raise HTTPException(status_code=500, detail=transfer_result.get("error", "Transfer failed"))
    elif transfer_status in ["pending", "otp"]:
        # API success, but transfer requires processing/OTP
        is_pending = True
        logger.info(f"[WITHDRAWAL] Transfer pending: {transfer_status}")
    
    # Even "success" might mean it's just successfully queued. 
    # For Registered Business, it typically returns "success" or "pending".
    # We will trust "success" as completed unless we want to be very strict and wait for webhook for ALL.
    # Given the user wants `approve-transfer`, they definitely expect some to be pending.

    
    # Step 3: Deduct from wallet balance
    from decimal import Decimal
    profile.wallet_balance = Decimal(str(current_balance)) - Decimal(str(withdraw_amount))
    
    # Record the withdrawal transaction
    withdrawal_txn = CreatorTransaction(
        profile_id=profile.id,
        paystack_reference=transfer_result.get("reference") if not is_pending else f"PENDING_{recipient_code}",
        fan_phone=request.mpesa_number,
        gross_amount=-withdraw_amount,  # Negative for withdrawal
        platform_fee=0,
        creator_amount=-withdraw_amount,
        status="pending" if is_pending else "completed"
    )
    db.add(withdrawal_txn)
    
    await db.commit()
    
    if is_pending:
        return {
            "success": True,
            "message": f"Withdrawal of KES {withdraw_amount} approved! Waiting for disbursement to {request.mpesa_number}.",
            "status": "pending",
            "new_balance": float(profile.wallet_balance)
        }
    
    return {
        "success": True,
        "message": f"KES {withdraw_amount} sent to {request.mpesa_number}",
        "transfer_code": transfer_result.get("transfer_code"),
        "new_balance": float(profile.wallet_balance)
    }


@router.get("/debug/paystack-banks")
async def get_paystack_banks(
    user: User = Depends(get_current_user)
):
    """
    Debug endpoint: Fetch available Paystack banks/mobile money providers for Kenya.
    """
    import requests
    
    payment_service = PaymentService()
    
    url = f"{payment_service.paystack_base_url}/bank"
    headers = {
        "Authorization": f"Bearer {payment_service.paystack_secret_key}",
    }
    
    params = {
        "country": "kenya",
        "perPage": 100
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        result = response.json()
        
        if result.get("status"):
            banks = result.get("data", [])
            # Filter for mobile money
            mobile_money = [b for b in banks if b.get("type") == "mobile_money" or "mobile" in b.get("name", "").lower() or "mpesa" in b.get("name", "").lower()]
            return {
                "all_banks_count": len(banks),
                "mobile_money_providers": mobile_money,
                "all_banks": banks[:20]  # First 20 for reference
            }
        else:
            return {"error": result.get("message"), "raw": result}
    except Exception as e:
        return {"error": str(e)}


@router.get("/premium-links/my")
async def get_my_premium_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all premium links created by the current user."""
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        return []
    
    links_stmt = select(PremiumLink).filter(PremiumLink.profile_id == profile.id)
    links_res = await db.execute(links_stmt)
    links = links_res.scalars().all()
    
    return [
        {
            "id": l.id,
            "title": l.title,
            "price": float(l.price),
            "description": l.description,
            "is_active": l.is_active,
            "total_sales": l.total_sales,
            "total_revenue": float(l.total_revenue or 0),
            "public_url": f"/unlock/{l.id}"
        } for l in links
    ]


# ============================================================================
# Media Kit Endpoint
# ============================================================================

@router.get("/media-kit")
async def get_media_kit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get creator media kit data for professional brand pitches."""
    profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=400, detail="Connect TikTok first")
    
    # Calculate engagement rate
    total_engagement = (profile.likes_count or 0)
    engagement_rate = 0.0
    if profile.follower_count and profile.follower_count > 0:
        engagement_rate = (total_engagement / profile.follower_count) * 100
    
    # Estimate rates based on Kenyan market (rough heuristic)
    # Nano: 1k-10k followers -> KES 1,000-5,000
    # Micro: 10k-50k followers -> KES 5,000-15,000
    # Macro: 50k-500k followers -> KES 15,000-50,000
    # Mega: 500k+ followers -> KES 50,000+
    followers = profile.follower_count or 0
    if followers < 10000:
        rate_min, rate_max = 1000, 5000
    elif followers < 50000:
        rate_min, rate_max = 5000, 15000
    elif followers < 500000:
        rate_min, rate_max = 15000, 50000
    else:
        rate_min, rate_max = 50000, 150000
    
    return {
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "follower_count": profile.follower_count,
        "following_count": profile.following_count,
        "likes_count": profile.likes_count,
        "video_count": profile.video_count,
        "engagement_rate": f"{engagement_rate:.2f}%",
        "suggested_rate_range": {
            "min": rate_min,
            "max": rate_max,
            "currency": "KES"
        },
        "profile_url": f"https://www.tiktok.com/@{profile.username}" if profile.username else None,
        "media_kit_url": f"/creator/{profile.username}/kit" if profile.username else None
    }


# ============================================================================
# Public Link Access (No Auth Required)
# ============================================================================

@router.get("/public/link/{link_id}")
async def get_public_link_info(
    link_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get public info for a premium link (for the unlock page)."""
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    if not link.is_active:
        raise HTTPException(status_code=400, detail="This link is no longer available")
    
    # Get creator info
    profile = await db.get(TikTokProfile, link.profile_id)
    
    return {
        "id": link.id,
        "title": link.title,
        "description": link.description,
        "price": float(link.price),
        "creator": {
            "username": profile.username if profile else None,
            "display_name": profile.display_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None
        }
    }


# ============================================================================
# Phase 1: Tip Jar Endpoints
# ============================================================================

from ..models import TipTransaction, LinkClickAnalytics, FanContact
import hashlib

class TipRequest(BaseModel):
    creator_username: str
    email: str
    amount: float  # KES
    name: Optional[str] = None
    message: Optional[str] = None
    callback_url: Optional[str] = None


@router.post("/public/tip")
async def initiate_tip(
    request: TipRequest,
    db: AsyncSession = Depends(get_db)
):
    """Initiate a tip payment to a creator (no auth required)."""
    # Find creator by username
    result = await db.execute(
        select(TikTokProfile).where(TikTokProfile.username == request.creator_username)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    
    # Validate amount (minimum tip: KES 10)
    if request.amount < 10:
        raise HTTPException(status_code=400, detail="Minimum tip is KES 10")
    
    # Calculate fees (10% platform fee)
    platform_fee = round(request.amount * 0.10, 2)
    creator_amount = round(request.amount - platform_fee, 2)
    
    # Create tip transaction
    tip = TipTransaction(
        profile_id=profile.id,
        fan_email=request.email,
        fan_name=request.name,
        fan_message=request.message,
        amount=request.amount,
        platform_fee=platform_fee,
        creator_amount=creator_amount,
        status="pending"
    )
    db.add(tip)
    await db.commit()
    await db.refresh(tip)
    
    # Create Paystack payment
    payment_service = PaymentService()
    
    try:
        result = await payment_service.initiate_payment(
            email=request.email,
            amount=int(request.amount * 100),  # Amount in kobo (KES cents)
            currency="KES",
            reference=f"TIP-{tip.id}-{int(datetime.utcnow().timestamp())}",
            callback_url=request.callback_url,
            metadata={
                "tip_id": tip.id,
                "creator_username": profile.username,
                "type": "tip"
            }
        )
        
        # Update tip with reference
        tip.paystack_reference = result.get("reference")
        await db.commit()
        
        return {
            "authorization_url": result.get("authorization_url"),
            "reference": result.get("reference"),
            "tip_id": tip.id,
            "amount": float(request.amount),
            "creator_display_name": profile.display_name
        }
        
    except Exception as e:
        logger.error(f"Failed to initiate tip payment: {e}")
        raise HTTPException(status_code=500, detail="Payment initialization failed")


@router.post("/public/tip/{tip_id}/verify")
async def verify_tip(
    tip_id: int,
    reference: str,
    db: AsyncSession = Depends(get_db)
):
    """Verify a tip payment and credit creator wallet."""
    tip = await db.get(TipTransaction, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    if tip.status == "completed":
        return {"message": "Tip already processed", "status": "completed"}
    
    # Verify with Paystack
    payment_service = PaymentService()
    
    try:
        verification = await payment_service.verify_transaction(reference)
        
        if verification.get("status") == "success":
            # Update tip status
            tip.status = "completed"
            
            # Credit creator wallet
            profile = await db.get(TikTokProfile, tip.profile_id)
            if profile:
                profile.wallet_balance = float(profile.wallet_balance or 0) + float(tip.creator_amount)
                profile.total_earned = float(profile.total_earned or 0) + float(tip.creator_amount)
            
            # Save fan contact
            await _save_fan_contact(
                db, 
                profile.id, 
                tip.fan_email, 
                tip.fan_name, 
                None,
                "tip", 
                None,
                float(tip.amount)
            )
            
            await db.commit()
            
            return {
                "status": "success",
                "message": f"Thank you for supporting {profile.display_name}!",
                "amount": float(tip.amount)
            }
        else:
            tip.status = "failed"
            await db.commit()
            raise HTTPException(status_code=400, detail="Payment verification failed")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tip verification error: {e}")
        raise HTTPException(status_code=500, detail="Verification failed")


@router.get("/tips")
async def get_my_tips(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all tips received by the current creator."""
    profile = await db.execute(
        select(TikTokProfile).where(TikTokProfile.user_id == user.id)
    )
    profile = profile.scalar_one_or_none()
    
    if not profile:
        return {"tips": [], "total_tips": 0, "total_amount": 0}
    
    result = await db.execute(
        select(TipTransaction)
        .where(TipTransaction.profile_id == profile.id)
        .where(TipTransaction.status == "completed")
        .order_by(TipTransaction.created_at.desc())
        .limit(50)
    )
    tips = result.scalars().all()
    
    total_amount = sum(float(t.creator_amount) for t in tips)
    
    return {
        "tips": [
            {
                "id": t.id,
                "amount": float(t.amount),
                "creator_amount": float(t.creator_amount),
                "fan_name": t.fan_name or "Anonymous",
                "fan_message": t.fan_message,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in tips
        ],
        "total_tips": len(tips),
        "total_amount": total_amount
    }


# ============================================================================
# Phase 1: Link Analytics Endpoints
# ============================================================================

@router.post("/public/link/{link_id}/track")
async def track_link_event(
    link_id: int,
    request: Request,
    event_type: str = "view",  # view, click
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Track a view or click on a premium link (for analytics)."""
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    # Get request metadata
    referrer = request.headers.get("referer", "")
    user_agent = request.headers.get("user-agent", "")
    
    # Hash IP for privacy
    client_ip = request.client.host if request.client else ""
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16] if client_ip else None
    
    # Detect source from referrer
    detected_source = source
    if not detected_source and referrer:
        if "tiktok" in referrer.lower():
            detected_source = "tiktok"
        elif "whatsapp" in referrer.lower():
            detected_source = "whatsapp"
        elif "instagram" in referrer.lower():
            detected_source = "instagram"
        elif "twitter" in referrer.lower() or "x.com" in referrer.lower():
            detected_source = "twitter"
        else:
            detected_source = "other"
    
    # Create analytics event
    event = LinkClickAnalytics(
        premium_link_id=link_id,
        event_type=event_type,
        referrer=referrer[:500] if referrer else None,  # Limit length
        source=detected_source,
        user_agent=user_agent[:500] if user_agent else None,
        ip_hash=ip_hash
    )
    db.add(event)
    await db.commit()
    
    return {"tracked": True}


@router.get("/links/{link_id}/analytics")
async def get_link_analytics(
    link_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get analytics for a premium link (owner only)."""
    # Verify ownership
    link = await db.get(PremiumLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    profile = await db.execute(
        select(TikTokProfile).where(TikTokProfile.user_id == user.id)
    )
    profile = profile.scalar_one_or_none()
    
    if not profile or link.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get analytics summary
    from sqlalchemy import and_
    from datetime import timedelta
    
    now = datetime.utcnow()
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)
    
    # Total counts
    result = await db.execute(
        select(
            LinkClickAnalytics.event_type,
            func.count(LinkClickAnalytics.id)
        )
        .where(LinkClickAnalytics.premium_link_id == link_id)
        .group_by(LinkClickAnalytics.event_type)
    )
    event_counts = dict(result.all())
    
    # Source breakdown
    result = await db.execute(
        select(
            LinkClickAnalytics.source,
            func.count(LinkClickAnalytics.id)
        )
        .where(LinkClickAnalytics.premium_link_id == link_id)
        .where(LinkClickAnalytics.event_type == "view")
        .group_by(LinkClickAnalytics.source)
    )
    source_breakdown = dict(result.all())
    
    # Last 7 days trend
    result = await db.execute(
        select(func.count(LinkClickAnalytics.id))
        .where(LinkClickAnalytics.premium_link_id == link_id)
        .where(LinkClickAnalytics.event_type == "view")
        .where(LinkClickAnalytics.created_at >= last_7_days)
    )
    views_7d = result.scalar() or 0
    
    # Calculate conversion rate
    total_views = event_counts.get("view", 0)
    total_purchases = int(link.total_sales or 0)
    conversion_rate = (total_purchases / total_views * 100) if total_views > 0 else 0
    
    return {
        "link_id": link_id,
        "title": link.title,
        "metrics": {
            "total_views": event_counts.get("view", 0),
            "total_clicks": event_counts.get("click", 0),
            "total_purchases": total_purchases,
            "conversion_rate": round(conversion_rate, 2),
            "total_revenue": float(link.total_revenue or 0),
            "views_last_7_days": views_7d
        },
        "sources": source_breakdown
    }


# ============================================================================
# Phase 1: Fan Contact Management
# ============================================================================

async def _save_fan_contact(
    db: AsyncSession,
    profile_id: int,
    email: str,
    name: Optional[str],
    phone: Optional[str],
    source_type: str,
    source_link_id: Optional[int],
    amount_spent: float
):
    """Helper to save or update a fan contact."""
    if not email:
        return None
        
    # Check if contact exists
    result = await db.execute(
        select(FanContact)
        .where(FanContact.profile_id == profile_id)
        .where(FanContact.email == email)
    )
    contact = result.scalar_one_or_none()
    
    if contact:
        # Update existing
        contact.total_spent = float(contact.total_spent or 0) + amount_spent
        contact.purchase_count = (contact.purchase_count or 0) + 1
        if name and not contact.name:
            contact.name = name
        if phone and not contact.phone:
            contact.phone = phone
    else:
        # Create new
        contact = FanContact(
            profile_id=profile_id,
            email=email,
            name=name,
            phone=phone,
            source_type=source_type,
            source_link_id=source_link_id,
            total_spent=amount_spent,
            purchase_count=1
        )
        db.add(contact)
    
    return contact


@router.get("/fans")
async def get_my_fans(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all fan contacts for the current creator."""
    profile = await db.execute(
        select(TikTokProfile).where(TikTokProfile.user_id == user.id)
    )
    profile = profile.scalar_one_or_none()
    
    if not profile:
        return {"fans": [], "total_fans": 0, "total_lifetime_value": 0}
    
    result = await db.execute(
        select(FanContact)
        .where(FanContact.profile_id == profile.id)
        .order_by(FanContact.total_spent.desc())
        .limit(100)
    )
    fans = result.scalars().all()
    
    total_ltv = sum(float(f.total_spent or 0) for f in fans)
    
    return {
        "fans": [
            {
                "id": f.id,
                "email": f.email,
                "name": f.name,
                "phone": f.phone,
                "source_type": f.source_type,
                "total_spent": float(f.total_spent or 0),
                "purchase_count": f.purchase_count,
                "created_at": f.created_at.isoformat() if f.created_at else None
            }
            for f in fans
        ],
        "total_fans": len(fans),
        "total_lifetime_value": total_ltv
    }


@router.get("/fans/export")
async def export_fans_csv(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Export fan contacts as CSV."""
    from fastapi.responses import StreamingResponse
    import io
    import csv
    
    profile = await db.execute(
        select(TikTokProfile).where(TikTokProfile.user_id == user.id)
    )
    profile = profile.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="No TikTok profile found")
    
    result = await db.execute(
        select(FanContact)
        .where(FanContact.profile_id == profile.id)
        .order_by(FanContact.created_at.desc())
    )
    fans = result.scalars().all()
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Name", "Phone", "Source", "Total Spent (KES)", "Purchases", "First Contact"])
    
    for f in fans:
        writer.writerow([
            f.email,
            f.name or "",
            f.phone or "",
            f.source_type,
            float(f.total_spent or 0),
            f.purchase_count,
            f.created_at.strftime("%Y-%m-%d") if f.created_at else ""
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fans_{profile.username}_{datetime.utcnow().strftime('%Y%m%d')}.csv"}
    )

