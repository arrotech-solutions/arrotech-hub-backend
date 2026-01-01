"""
Email notification service for Mini-Hub.
Supports SMTP email sending for various notification types.
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending email notifications."""
    
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@minihub.ai")
        self.from_name = os.getenv("FROM_NAME", "Mini-Hub")
        self.enabled = bool(self.smtp_user and self.smtp_password)
    
    def _get_base_template(self, content: str, title: str = "Mini-Hub Notification") -> str:
        """Get the base HTML email template."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #8B5CF6 0%, #EC4899 100%);
                    padding: 30px;
                    text-align: center;
                    border-radius: 12px 12px 0 0;
                }}
                .header h1 {{
                    color: white;
                    margin: 0;
                    font-size: 28px;
                }}
                .content {{
                    background: white;
                    padding: 30px;
                    border-radius: 0 0 12px 12px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                }}
                .button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #8B5CF6 0%, #EC4899 100%);
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: 600;
                    margin: 20px 0;
                }}
                .button:hover {{
                    opacity: 0.9;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #666;
                    font-size: 12px;
                }}
                .stats-box {{
                    background: #f8f9fa;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .stat {{
                    display: inline-block;
                    text-align: center;
                    padding: 10px 20px;
                }}
                .stat-value {{
                    font-size: 24px;
                    font-weight: bold;
                    color: #8B5CF6;
                }}
                .stat-label {{
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚀 Mini-Hub</h1>
                </div>
                <div class="content">
                    {content}
                </div>
                <div class="footer">
                    <p>© 2024 Mini-Hub. All rights reserved.</p>
                    <p>
                        <a href="{{{{unsubscribe_url}}}}">Unsubscribe</a> | 
                        <a href="{{{{settings_url}}}}">Email Preferences</a>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """Send an email asynchronously."""
        if not self.enabled:
            logger.warning("Email service is not configured. Skipping email.")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add text version
            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            
            # Add HTML version
            msg.attach(MIMEText(html_content, 'html'))
            
            # Send email in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def _send_smtp(self, msg: MIMEMultipart) -> None:
        """Send email via SMTP (blocking)."""
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
    
    # ================== Notification Templates ==================
    
    async def send_welcome_email(self, to_email: str, user_name: str) -> bool:
        """Send welcome email to new users."""
        content = f"""
        <h2>Welcome to Mini-Hub, {user_name}! 🎉</h2>
        <p>We're thrilled to have you join our community of workflow creators and automation enthusiasts.</p>
        
        <h3>Here's what you can do:</h3>
        <ul>
            <li>🤖 <strong>Chat with AI</strong> - Use natural language to interact with your tools</li>
            <li>🔄 <strong>Create Workflows</strong> - Automate repetitive tasks</li>
            <li>🏪 <strong>Explore Marketplace</strong> - Discover workflows from other creators</li>
            <li>💰 <strong>Monetize</strong> - Share and sell your workflows</li>
        </ul>
        
        <a href="https://minihub.ai/dashboard" class="button">Get Started</a>
        
        <p>If you have any questions, our team is here to help!</p>
        """
        
        html = self._get_base_template(content, "Welcome to Mini-Hub!")
        return await self.send_email(to_email, "🚀 Welcome to Mini-Hub!", html)
    
    async def send_workflow_download_notification(
        self,
        to_email: str,
        creator_name: str,
        workflow_name: str,
        buyer_name: str,
        download_count: int
    ) -> bool:
        """Send notification when someone downloads a workflow."""
        content = f"""
        <h2>Someone downloaded your workflow! 🎉</h2>
        <p>Hi {creator_name},</p>
        <p><strong>{buyer_name}</strong> just downloaded your workflow <strong>"{workflow_name}"</strong>.</p>
        
        <div class="stats-box">
            <div class="stat">
                <div class="stat-value">{download_count}</div>
                <div class="stat-label">Total Downloads</div>
            </div>
        </div>
        
        <a href="https://minihub.ai/creator-profile" class="button">View Your Dashboard</a>
        """
        
        html = self._get_base_template(content, "New Download!")
        return await self.send_email(to_email, f"🎉 {buyer_name} downloaded your workflow!", html)
    
    async def send_workflow_sale_notification(
        self,
        to_email: str,
        creator_name: str,
        workflow_name: str,
        buyer_name: str,
        amount: float,
        currency: str,
        total_earnings: float
    ) -> bool:
        """Send notification when a workflow is purchased."""
        content = f"""
        <h2>You made a sale! 💰</h2>
        <p>Hi {creator_name},</p>
        <p><strong>{buyer_name}</strong> just purchased your workflow <strong>"{workflow_name}"</strong> for <strong>{currency} {amount:.2f}</strong>!</p>
        
        <div class="stats-box">
            <div class="stat">
                <div class="stat-value">{currency} {amount:.2f}</div>
                <div class="stat-label">This Sale</div>
            </div>
            <div class="stat">
                <div class="stat-value">{currency} {total_earnings:.2f}</div>
                <div class="stat-label">Total Earnings</div>
            </div>
        </div>
        
        <a href="https://minihub.ai/creator-profile" class="button">View Earnings</a>
        """
        
        html = self._get_base_template(content, "New Sale!")
        return await self.send_email(to_email, f"💰 You earned {currency} {amount:.2f}!", html)
    
    async def send_new_follower_notification(
        self,
        to_email: str,
        creator_name: str,
        follower_name: str,
        total_followers: int
    ) -> bool:
        """Send notification when someone follows the creator."""
        content = f"""
        <h2>New Follower! 👥</h2>
        <p>Hi {creator_name},</p>
        <p><strong>{follower_name}</strong> is now following you!</p>
        
        <div class="stats-box">
            <div class="stat">
                <div class="stat-value">{total_followers}</div>
                <div class="stat-label">Total Followers</div>
            </div>
        </div>
        
        <p>Keep creating amazing workflows to grow your audience!</p>
        
        <a href="https://minihub.ai/creator-profile" class="button">View Profile</a>
        """
        
        html = self._get_base_template(content, "New Follower!")
        return await self.send_email(to_email, f"👥 {follower_name} is now following you!", html)
    
    async def send_new_review_notification(
        self,
        to_email: str,
        creator_name: str,
        workflow_name: str,
        reviewer_name: str,
        rating: int,
        review_text: Optional[str] = None
    ) -> bool:
        """Send notification when someone reviews a workflow."""
        stars = "⭐" * rating
        content = f"""
        <h2>New Review! {stars}</h2>
        <p>Hi {creator_name},</p>
        <p><strong>{reviewer_name}</strong> left a {rating}-star review on your workflow <strong>"{workflow_name}"</strong>.</p>
        
        {f'<blockquote style="border-left: 4px solid #8B5CF6; padding-left: 15px; margin: 20px 0; color: #555;">"{review_text}"</blockquote>' if review_text else ''}
        
        <a href="https://minihub.ai/marketplace" class="button">View Review</a>
        """
        
        html = self._get_base_template(content, "New Review!")
        return await self.send_email(to_email, f"{stars} New {rating}-star review on {workflow_name}!", html)
    
    async def send_weekly_summary(
        self,
        to_email: str,
        creator_name: str,
        stats: Dict
    ) -> bool:
        """Send weekly performance summary."""
        content = f"""
        <h2>Your Weekly Summary 📊</h2>
        <p>Hi {creator_name},</p>
        <p>Here's how your workflows performed this week:</p>
        
        <div class="stats-box">
            <div class="stat">
                <div class="stat-value">{stats.get('downloads', 0)}</div>
                <div class="stat-label">Downloads</div>
            </div>
            <div class="stat">
                <div class="stat-value">{stats.get('views', 0)}</div>
                <div class="stat-label">Views</div>
            </div>
            <div class="stat">
                <div class="stat-value">${stats.get('earnings', 0):.2f}</div>
                <div class="stat-label">Earnings</div>
            </div>
            <div class="stat">
                <div class="stat-value">{stats.get('new_followers', 0)}</div>
                <div class="stat-label">New Followers</div>
            </div>
        </div>
        
        <h3>Top Performing Workflows</h3>
        <ol>
        {''.join([f'<li><strong>{wf["name"]}</strong> - {wf["downloads"]} downloads</li>' for wf in stats.get('top_workflows', [])])}
        </ol>
        
        <a href="https://minihub.ai/creator-profile" class="button">View Full Analytics</a>
        """
        
        html = self._get_base_template(content, "Your Weekly Summary")
        return await self.send_email(to_email, "📊 Your Mini-Hub Weekly Summary", html)
    
    async def send_payment_received_notification(
        self,
        to_email: str,
        user_name: str,
        amount: float,
        currency: str,
        payment_method: str,
        item_name: str
    ) -> bool:
        """Send payment confirmation email."""
        content = f"""
        <h2>Payment Successful! ✅</h2>
        <p>Hi {user_name},</p>
        <p>Your payment of <strong>{currency} {amount:.2f}</strong> via {payment_method} was successful.</p>
        
        <div class="stats-box">
            <p><strong>Item:</strong> {item_name}</p>
            <p><strong>Amount:</strong> {currency} {amount:.2f}</p>
            <p><strong>Payment Method:</strong> {payment_method}</p>
        </div>
        
        <p>The workflow has been added to your library and is ready to use.</p>
        
        <a href="https://minihub.ai/workflows" class="button">View Your Workflows</a>
        """
        
        html = self._get_base_template(content, "Payment Confirmation")
        return await self.send_email(to_email, f"✅ Payment of {currency} {amount:.2f} confirmed", html)
    
    async def send_workflow_published_notification(
        self,
        to_email: str,
        creator_name: str,
        workflow_name: str,
        visibility: str
    ) -> bool:
        """Send notification when a workflow is published to marketplace."""
        visibility_text = "publicly available" if visibility == "marketplace" else "shared with your link"
        content = f"""
        <h2>Workflow Published! 🎉</h2>
        <p>Hi {creator_name},</p>
        <p>Your workflow <strong>"{workflow_name}"</strong> is now {visibility_text}!</p>
        
        <h3>Next Steps:</h3>
        <ul>
            <li>Share the link with your network</li>
            <li>Add detailed descriptions and tags</li>
            <li>Respond to reviews and questions</li>
        </ul>
        
        <a href="https://minihub.ai/marketplace" class="button">View in Marketplace</a>
        """
        
        html = self._get_base_template(content, "Workflow Published!")
        return await self.send_email(to_email, f"🎉 {workflow_name} is now live!", html)
    
    async def send_password_reset_email(
        self,
        to_email: str,
        reset_token: str,
        reset_url: str
    ) -> bool:
        """Send password reset email."""
        content = f"""
        <h2>Reset Your Password 🔐</h2>
        <p>We received a request to reset your password. Click the button below to set a new password:</p>
        
        <a href="{reset_url}?token={reset_token}" class="button">Reset Password</a>
        
        <p style="margin-top: 30px; color: #666; font-size: 14px;">
            If you didn't request this, you can safely ignore this email. The link will expire in 1 hour.
        </p>
        """
        
        html = self._get_base_template(content, "Reset Your Password")
        return await self.send_email(to_email, "🔐 Reset your Mini-Hub password", html)


# Create singleton instance
email_service = EmailService()

