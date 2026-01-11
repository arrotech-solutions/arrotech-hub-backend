
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.future import select
from ..database import async_session_factory
from ..models import User, SubscriptionStatus, SubscriptionTier
from ..services.notification_service import NotificationService # Assuming this exists or will mock

logger = logging.getLogger(__name__)

class SubscriptionWorker:
    def __init__(self):
        self.notification_service = NotificationService()

    async def check_subscriptions(self):
        """Check for expired subscriptions and handle grace periods."""
        logger.info("Starting subscription check...")
        
        async with async_session_factory() as db:
            try:
                # Get all users with expiration dates in the past
                now = datetime.now()
                # Query logic: active users whose end_date is < now
                # We also need to check grace_period users who might have now fully expired
                result = await db.execute(
                    select(User).where(
                        (User.subscription_end_date.isnot(None)) & 
                        (User.subscription_end_date < now) &
                        (User.subscription_status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE_PERIOD]))
                    )
                )
                users = result.scalars().all()
                
                for user in users:
                    days_past_due = (now - user.subscription_end_date).days
                    
                    if days_past_due <= 7:
                        # Grace Period
                        if user.subscription_status != SubscriptionStatus.GRACE_PERIOD:
                            logger.info(f"User {user.email} entering grace period.")
                            user.subscription_status = SubscriptionStatus.GRACE_PERIOD
                            # await self.notification_service.send_email(
                            #     user.email, 
                            #     "Subscription Payment Due - Grace Period",
                            #     "Your subscription has expired. You have 7 days to renew."
                            # )
                    else:
                        # Expired - Downgrade
                        if user.subscription_status != SubscriptionStatus.EXPIRED:
                            logger.info(f"User {user.email} expired. Downgrading to Free.")
                            user.subscription_status = SubscriptionStatus.EXPIRED
                            user.subscription_tier = SubscriptionTier.FREE
                            # await self.notification_service.send_email(
                            #     user.email, 
                            #     "Subscription Expired",
                            #     "Your subscription currently ended. You have been moved to the Free tier."
                            # )
                            
                await db.commit()
                logger.info(f"Processed {len(users)} users for subscription check.")
                
            except Exception as e:
                logger.error(f"Error in subscription worker: {e}")
                await db.rollback()

async def run_worker_loop():
    worker = SubscriptionWorker()
    while True:
        await worker.check_subscriptions()
        # Run daily
        await asyncio.sleep(86400) 

if __name__ == "__main__":
    asyncio.run(run_worker_loop())
