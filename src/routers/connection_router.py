"""
Connection management router for Mini-Hub.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.asana_service import AsanaService
from ..services.ga4_service import GA4Service
from ..services.hubspot_service import HubSpotService
from ..services.platform_registry import platform_registry
from ..services.powerbi_service import PowerBIService
from ..services.slack_service import SlackService
from ..services.teams_service import TeamsService
from ..services.whatsapp_service import WhatsAppService
from ..services.zoom_service import ZoomService
from ..services.hr_service import HRService
from ..services.logistics_service import LogisticsService
from ..services.lead_intelligence_service import LeadIntelligenceService
from ..services.bilingual_service import BilingualService

router = APIRouter()

# Initialize services
hubspot_service = HubSpotService()
ga4_service = GA4Service()
slack_service = SlackService()
teams_service = TeamsService()
zoom_service = ZoomService()
whatsapp_service = WhatsAppService()
asana_service = AsanaService()
powerbi_service = PowerBIService()
hr_service = HRService()
logistics_service = LogisticsService()
lead_service = LeadIntelligenceService()
context_service = BilingualService()


class ConnectionCreate(BaseModel):
    platform: str
    name: str
    config: Dict[str, Any]


class ConnectionUpdate(BaseModel):
    name: str
    status: str
    config: Dict[str, Any]


@router.get("/")
async def get_connections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's connections."""
    try:
        result = await db.execute(
            select(Connection)
            .filter(Connection.user_id == current_user.id)
            .options(selectinload(Connection.user))
        )
        connections = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": conn.id,
                    "platform": conn.platform,
                    "name": conn.name,
                    "status": conn.status,
                    "config": conn.config,
                    "last_sync": conn.last_sync,
                    "error_message": conn.error_message,
                    "created_at": conn.created_at,
                    "updated_at": conn.updated_at
                }
                for conn in connections
            ]
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get connections: {str(e)}"
        )


@router.post("/")
async def create_connection(
    connection_data: ConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new connection."""
    try:
        # Validate platform using platform registry
        platform = platform_registry.get_platform(connection_data.platform)
        if not platform:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platform: {connection_data.platform}. Available platforms: {[p.id for p in platform_registry.list_platforms()]}"
            )

        # Validate configuration using platform schema
        if not platform_registry.validate_platform_config(connection_data.platform, connection_data.config):
            schema = platform_registry.get_platform_config_schema(
                connection_data.platform)
            required_fields = schema.get("required", []) if schema else []
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid configuration. Required fields: {required_fields}"
            )

        # Test connection based on platform
        test_result = await test_platform_connection(
            connection_data.platform,
            connection_data.config
        )

        if not test_result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Connection test failed: {test_result['error']}"
            )

        # Create connection
        connection = Connection(
            user_id=current_user.id,
            platform=connection_data.platform,
            name=connection_data.name,
            status=ConnectionStatus.ACTIVE,
            config=connection_data.config
        )

        db.add(connection)
        await db.commit()
        await db.refresh(connection)

        return {
            "success": True,
            "data": {
                "id": connection.id,
                "platform": connection.platform,
                "name": connection.name,
                "status": connection.status,
                "created_at": connection.created_at
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create connection: {str(e)}"
        )


@router.put("/{connection_id}")
async def update_connection(
    connection_id: int,
    connection_data: ConnectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a connection."""
    try:
        result = await db.execute(
            select(Connection)
            .filter(Connection.id == connection_id, Connection.user_id == current_user.id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Update connection
        connection.name = connection_data.name
        connection.status = connection_data.status
        connection.config = connection_data.config
        
        await db.commit()
        await db.refresh(connection)

        return {
            "success": True,
            "data": {
                "id": connection.id,
                "platform": connection.platform,
                "name": connection.name,
                "status": connection.status,
                "updated_at": connection.updated_at
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update connection: {str(e)}"
        )


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a connection."""
    try:
        result = await db.execute(
            select(Connection)
            .filter(Connection.id == connection_id, Connection.user_id == current_user.id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        await db.delete(connection)
        await db.commit()

        return {
            "success": True,
            "message": "Connection deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete connection: {str(e)}"
        )


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Test a connection."""
    try:
        result = await db.execute(
            select(Connection)
            .filter(Connection.id == connection_id, Connection.user_id == current_user.id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Test connection
        test_result = await test_platform_connection(
            connection.platform,
            connection.config
        )

        # Update connection status based on test result
        new_status = ConnectionStatus.ACTIVE if test_result["success"] else ConnectionStatus.ERROR
        await db.execute(
            update(Connection)
            .where(Connection.id == connection_id)
            .values(
                status=new_status,
                error_message=test_result.get(
                    "error") if not test_result["success"] else None
            )
        )
        await db.commit()

        return {
            "success": True,
            "data": {
                "connection_id": connection_id,
                "status": new_status,
                "test_result": test_result
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test connection: {str(e)}"
        )


async def test_platform_connection(platform: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Test connection for a specific platform."""
    try:
        if platform == "hubspot":
            return await hubspot_service.test_connection(config)
        elif platform == "ga4":
            return await ga4_service.test_connection(config)
        elif platform == "slack":
            return await slack_service.test_connection(config)
        elif platform == "whatsapp":
            return await whatsapp_service.test_connection(config)
        elif platform == "facebook":
            return await test_facebook_connection(config)
        elif platform == "twitter":
            return await test_twitter_connection(config)
        elif platform == "linkedin":
            return await test_linkedin_connection(config)
        elif platform == "instagram":
            return await test_instagram_connection(config)
        elif platform == "salesforce":
            return await test_salesforce_connection(config)
        elif platform == "teams":
            return await test_teams_connection(config)
        elif platform == "zoom":
            return await test_zoom_connection(config)
        elif platform == "asana":
            return await test_asana_connection(config)
        elif platform == "powerbi":
            return await powerbi_service.test_connection(config)
        elif platform == "hr_hub":
            return await hr_service.test_connection(config)
        elif platform == "logistics_hub":
            return await logistics_service.test_connection(config)
        elif platform == "lead_intelligence":
            return await lead_service.test_connection(config)
        elif platform == "context_intelligence":
            return await context_service.test_connection(config)
        else:
            return {
                "success": False,
                "error": f"Unsupported platform: {platform}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Connection test failed: {str(e)}"
        }


async def test_facebook_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Facebook connection."""
    try:
        # Mock test for now - would validate access token and page access
        access_token = config.get("access_token")
        page_id = config.get("page_id")
        
        if not access_token or not page_id:
            return {
                "success": False,
                "error": "Facebook access token and page ID are required"
            }
        
        # In a real implementation, you would:
        # 1. Validate the access token with Facebook Graph API
        # 2. Check if the page is accessible
        # 3. Verify permissions
        
        return {
            "success": True,
            "message": "Facebook connection test successful",
            "data": {
                "page_id": page_id,
                "permissions": ["pages_read_engagement", "pages_manage_posts"]
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Facebook connection test failed: {str(e)}"
        }


async def test_twitter_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Twitter connection."""
    try:
        # Mock test for now - would validate API credentials
        bearer_token = config.get("bearer_token")
        api_key = config.get("api_key")
        api_secret = config.get("api_secret")
        
        if not bearer_token or not api_key or not api_secret:
            return {
                "success": False,
                "error": "Twitter bearer token, API key, and API secret are required"
            }
        
        # In a real implementation, you would:
        # 1. Validate the bearer token with Twitter API
        # 2. Check API rate limits
        # 3. Verify account access
        
        return {
            "success": True,
            "message": "Twitter connection test successful",
            "data": {
                "api_version": "2.0",
                "rate_limit_remaining": 300
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Twitter connection test failed: {str(e)}"
        }


async def test_linkedin_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test LinkedIn connection."""
    try:
        # Mock test for now - would validate OAuth credentials
        access_token = config.get("access_token")
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        
        if not access_token or not client_id or not client_secret:
            return {
                "success": False,
                "error": "LinkedIn access token, client ID, and client secret are required"
            }
        
        # In a real implementation, you would:
        # 1. Validate the access token with LinkedIn API
        # 2. Check organization access
        # 3. Verify API permissions
        
        return {
            "success": True,
            "message": "LinkedIn connection test successful",
            "data": {
                "organization_id": config.get("organization_id"),
                "permissions": ["w_member_social", "r_organization_social"]
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"LinkedIn connection test failed: {str(e)}"
        }


async def test_instagram_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Instagram connection."""
    try:
        # Mock test for now - would validate Instagram Business API credentials
        access_token = config.get("access_token")
        instagram_business_account_id = config.get("instagram_business_account_id")
        
        if not access_token or not instagram_business_account_id:
            return {
                "success": False,
                "error": "Instagram access token and business account ID are required"
            }
        
        # In a real implementation, you would:
        # 1. Validate the access token with Instagram Graph API
        # 2. Check business account access
        # 3. Verify API permissions
        
        return {
            "success": True,
            "message": "Instagram connection test successful",
            "data": {
                "business_account_id": instagram_business_account_id,
                "permissions": ["instagram_basic", "instagram_content_publish"]
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Instagram connection test failed: {str(e)}"
        }


async def test_salesforce_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Salesforce connection."""
    try:
        # Validate required fields
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        username = config.get("username")
        password = config.get("password")
        security_token = config.get("security_token")
        
        if not all([client_id, client_secret, username, password, security_token]):
            return {
                "success": False,
                "error": "Salesforce client_id, client_secret, username, password, and security_token are required"
            }
        
        # Test authentication with Salesforce
        from ..services.salesforce_service import SalesforceService

        # Create a temporary connection object for testing
        class TempConnection:
            def __init__(self, config):
                self.config = config
        
        temp_connection = TempConnection(config)
        salesforce_service = SalesforceService()
        
        try:
            # Test authentication first
            await salesforce_service.initialize(temp_connection)
            
            # Test a simple API call to verify connection
            # Get available objects to test the connection
            result = await salesforce_service._make_request("GET", "/sobjects")
            
            if not result or not isinstance(result, dict):
                return {
                    "success": False,
                    "error": "Failed to retrieve Salesforce objects - authentication may have succeeded but API call failed"
                }
            
            return {
                "success": True,
                "message": "Salesforce connection test successful",
                "data": {
                    "instance_url": salesforce_service.instance_url,
                    "api_version": "v58.0",
                    "available_objects": list(result.keys()) if isinstance(result, dict) else [],
                    "total_objects": len(result.keys()) if isinstance(result, dict) else 0
                }
            }
            
        except Exception as auth_error:
            # Provide more detailed error information
            error_msg = str(auth_error)
            
            # Check for common Salesforce authentication errors
            if "invalid_grant" in error_msg.lower():
                return {
                    "success": False,
                    "error": "Invalid credentials. Please check your username, password, and security token.",
                    "details": error_msg
                }
            elif "invalid_client" in error_msg.lower():
                return {
                    "success": False,
                    "error": "Invalid client credentials. Please check your client_id and client_secret.",
                    "details": error_msg
                }
            elif "400" in error_msg:
                return {
                    "success": False,
                    "error": "Bad request to Salesforce. Please verify all credentials are correct and properly formatted.",
                    "details": error_msg
                }
            else:
                return {
                    "success": False,
                    "error": f"Salesforce authentication failed: {error_msg}",
                    "details": "Check your credentials and ensure your Salesforce account has API access enabled."
                }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Salesforce connection test failed: {str(e)}"
        }


async def test_teams_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Microsoft Teams connection."""
    try:
        # Test Teams connection using the service
        result = await teams_service.test_connection(config)
        
        if result.get("success"):
            return {
                "success": True,
                "message": "Teams connection test successful",
                "data": {
                    "method": result.get("method"),
                    "user": result.get("user")
                }
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Teams connection test failed")
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Teams connection test failed: {str(e)}"
        }


async def test_zoom_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Zoom connection."""
    try:
        # Test Zoom connection using the service
        result = await zoom_service.test_connection(config)
        
        if result.get("success"):
            return {
                "success": True,
                "message": "Zoom connection test successful",
                "data": {
                    "method": result.get("method"),
                    "user": result.get("user")
                }
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Zoom connection test failed")
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Zoom connection test failed: {str(e)}"
        }


async def test_ga4_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test GA4 connection."""
    try:
        # Create temporary service for testing
        ga4_service = GA4Service()
        
        # Test the connection
        result = await ga4_service.test_connection(config)
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": f"GA4 connection test failed: {str(e)}"
        }


async def test_asana_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Asana connection."""
    try:
        # Test Asana connection using the service
        result = await asana_service.test_connection(config)
        
        if result.get("success"):
            return {
                "success": True,
                "message": "Asana connection test successful",
                "data": {
                    "method": result.get("method"),
                    "user": result.get("user")
                }
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Asana connection test failed")
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Asana connection test failed: {str(e)}"
        }


async def test_powerbi_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test Power BI connection."""
    try:
        # Test Power BI connection using the service
        result = await powerbi_service.test_connection(config)
        
        if result.get("success"):
            return {
                "success": True,
                "message": "Power BI connection test successful",
                "data": {
                    "method": result.get("method"),
                    "user": result.get("user")
                }
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Power BI connection test failed")
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Power BI connection test failed: {str(e)}"
        }


@router.get("/platforms")
async def get_available_platforms():
    """Get available connection platforms from the platform registry."""
    try:
        platforms = platform_registry.list_platforms()

        return {
            "success": True,
            "data": {
                "platforms": [
                    {
                        "id": platform.id,
                        "name": platform.name,
                        "description": platform.description,
                        "icon": platform.icon,
                        "features": platform.features,
                        "capabilities": [
                            {
                                "name": cap.name,
                                "description": cap.description,
                                "tool_name": cap.tool_name,
                                "operations": cap.operations
                            }
                            for cap in platform.capabilities
                        ],
                        "config_schema": platform.config_schema
                    }
                    for platform in platforms
                ]
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get platforms: {str(e)}"
        )
