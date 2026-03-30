import httpx
import logging
import json
from typing import Dict, Any, Optional
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import settings
from ..models import TikTokProfile, Connection, ConnectionStatus

logger = logging.getLogger(__name__)

class TikTokService:
    """Service for interacting with TikTok API."""
    
    BASE_URL = "https://open.tiktokapis.com/v2"
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = httpx.AsyncClient(timeout=30.0)

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        url = f"{self.BASE_URL}/oauth/token/"
        data = {
            "client_key": settings.TIKTOK_CLIENT_KEY,
            "client_secret": settings.TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        response = await self.client.post(url, data=data, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"TikTok Token Exchange Failed: {response.text}")
            raise Exception("Failed to retrieve access token from TikTok")
            
        return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Fetch basic user info (avatar, name, stats)."""
        url = f"{self.BASE_URL}/user/info/"
        params = {
            "fields": "open_id,union_id,avatar_url,display_name,username,follower_count,following_count,likes_count,video_count"
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = await self.client.get(url, params=params, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"TikTok User Info Failed: {response.text}")
            raise Exception("Failed to fetch user info")
            
        data = response.json()
        return data.get("data", {}).get("user", {})

    async def sync_profile(self, user_id: uuid.UUID, auth_data: Dict[str, Any]) -> TikTokProfile:
        """Create or update TikTok profile in database."""
        access_token = auth_data.get("access_token")
        refresh_token = auth_data.get("refresh_token")
        open_id = auth_data.get("open_id")
        
        # 1. Fetch latest details from TikTok
        user_info = await self.get_user_info(access_token)
        
        # 2. Update Connection record
        connection_stmt = select(Connection).filter(
            Connection.user_id == user_id,
            Connection.platform == "tiktok"
        )
        result = await self.db.execute(connection_stmt)
        connection = result.scalar_one_or_none()
        
        config_update = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "open_id": open_id,
            "username": user_info.get("display_name"),
            "avatar_url": user_info.get("avatar_url")
        }
        
        if connection:
            connection.status = ConnectionStatus.ACTIVE
            connection.config = {**connection.config, **config_update}
        else:
            connection = Connection(
                user_id=user_id,
                platform="tiktok",
                name=f"TikTok ({user_info.get('display_name', 'User')})",
                status=ConnectionStatus.ACTIVE,
                config=config_update
            )
            self.db.add(connection)
            
        # 3. Update TikTokProfile record
        profile_stmt = select(TikTokProfile).filter(TikTokProfile.user_id == user_id)
        profile_res = await self.db.execute(profile_stmt)
        profile = profile_res.scalar_one_or_none()
        
        if not profile:
            profile = TikTokProfile(user_id=user_id)
            self.db.add(profile)
            
        profile.tiktok_user_id = open_id
        # Use username if available from API, otherwise create URL-safe version from display_name
        tiktok_username = user_info.get("username")
        if not tiktok_username:
            # Fallback: create URL-safe username from display_name
            # Replace spaces with underscores and make lowercase (like TikTok format)
            import re
            display = user_info.get("display_name", "")
            # Remove special chars, replace spaces with underscores, lowercase
            tiktok_username = re.sub(r'[^a-zA-Z0-9_]', '', display.replace(" ", "_")).lower() if display else None
        profile.username = tiktok_username
        logger.info(f"TIKTOK SYNC: Setting username='{tiktok_username}' from API or fallback")
        profile.display_name = user_info.get("display_name")
        profile.avatar_url = user_info.get("avatar_url")
        
        # Save extended stats
        logger.info(f"TIKTOK SYNC DEBUG: User Info Response: {user_info}")
        profile.follower_count = user_info.get("follower_count", 0)
        profile.following_count = user_info.get("following_count", 0)
        profile.likes_count = user_info.get("likes_count", 0)
        profile.video_count = user_info.get("video_count", 0)
        
        profile.accessToken = access_token
        profile.refreshToken = refresh_token
        profile.is_active = True
        
        # Note: 'follower_count' field might not be in the basic scope unless 'user.info.stats' is granted
        # and checking the response structure.
        # Assuming v2 response structure for now.
        
        await self.db.commit()
        await self.db.refresh(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test TikTok connection validity."""
        access_token = config.get("access_token")
        if not access_token:
            return {"success": False, "error": "No access token found"}
            
        try:
            # Simple validity check by fetching user info
            user = await self.get_user_info(access_token)
            return {
                "success": True, 
                "message": f"Connected as {user.get('display_name')}",
                "user": user
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        await self.client.aclose()

    async def publish_video(self, video_record) -> bool:
        """
        Orchestrate the video publishing flow.
        1. Init upload
        2. Upload file
        3. Create post
        """
        try:
            logger.info(f"Starting publish for video {video_record.id}")
            
            profile = await self.db.get(TikTokProfile, video_record.profile_id)
            if not profile or not profile.accessToken:
                logger.error(f"No profile/token for video {video_record.id}")
                return False

            # 1. Init Upload
            upload_url, publish_id = await self._init_upload(profile.accessToken, video_record)
            if not upload_url:
                return False
                
            # Save publish_id for tracking
            if publish_id:
                video_record.tiktok_video_id = publish_id
                # Commit early to save ID even if upload fails later? 
                # Better to commit only on success or have a "uploading" state.
                # For now, we update the object, and the caller commits it.
                
            # 2. Upload File
            # Assuming video_record.video_url contains the local path or accessible URL.
            file_path = video_record.video_url
            if not await self._upload_file_content(upload_url, file_path):
                return False
                
            logger.info(f"Video {video_record.id} published successfully to TikTok. Publish ID: {publish_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish video {video_record.id}: {e}")
            return False

    async def _init_upload(self, access_token: str, video_record) -> (Optional[str], Optional[str]):
        """
        Initialize video upload using TikTok V2 API.
        Returns: (upload_url, publish_id)
        POST /v2/post/publish/video/init/
        """
        url = f"{self.BASE_URL}/post/publish/video/init/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }
        
        # Calculate file size
        import os
        try:
            file_size = os.path.getsize(video_record.video_url)
        except OSError:
            logger.error(f"File not found: {video_record.video_url}")
            return None, None

        body = {
            "post_info": {
                "title": video_record.caption or "Uploaded via MiniHub",
                "privacy_level": video_record.privacy_level or "SELF_ONLY", 
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size, # Upload in one chunk for simplicity
                "total_chunk_count": 1
            }
        }
        
        try:
            response = await self.client.post(url, json=body, headers=headers)
            if response.status_code != 200:
                logger.error(f"TikTok Init Upload Failed: {response.text}")
                return None, None
                
            data = response.json()
            upload_url = data.get("data", {}).get("upload_url")
            publish_id = data.get("data", {}).get("publish_id")
            return upload_url, publish_id
        except Exception as e:
            logger.error(f"Exception in _init_upload: {e}")
            return None, None
        
    async def _upload_file_content(self, upload_url: str, file_path: str) -> bool:
        """
        Upload the actual binary file to the provided URL.
        """
        try:
            import aiofiles
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
            
            file_size = len(content)
                
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
                "Content-Range": f"bytes 0-{file_size - 1}/{file_size}"
            }
            
            response = await self.client.put(upload_url, content=content, headers=headers)
            
            if response.status_code not in [200, 201]:
                logger.error(f"TikTok Binary Upload Failed: {response.text}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return False

    async def check_publish_status(self, access_token: str, publish_id: str) -> Dict[str, Any]:
        """
        Check the status of a published video.
        GET /v2/post/publish/status/
        """
        url = f"{self.BASE_URL}/post/publish/status/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }
        params = {
            "publish_id": publish_id
        }
        
        try:
            response = await self.client.get(url, params=params, headers=headers)
            if response.status_code != 200:
                logger.error(f"TikTok Status Check Failed: {response.text}")
                return {"status": "ERROR", "details": response.text}
                
            return response.json()
        except Exception as e:
            logger.error(f"Exception in check_publish_status: {e}")
            return {"status": "EXCEPTION", "details": str(e)}
