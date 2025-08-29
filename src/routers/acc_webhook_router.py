"""
ACC Webhook Router

Endpoints to receive real-time webhook notifications from Autodesk Construction Cloud.
Replaces polling with efficient real-time event processing.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..services.acc_webhook_service import acc_webhook_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acc/webhooks", tags=["ACC Webhooks"])


@router.post("/events")
async def receive_webhook_event(
    request: Request,
    x_adsk_signature: str = Header(None, alias="X-Adsk-Signature"),
    content_type: str = Header(..., alias="Content-Type")
):
    """
    Receive and process ACC webhook events.
    
    This endpoint receives real-time notifications from Autodesk Construction Cloud
    when issues are created, modified, or deleted.
    """
    try:
        logger.info("🔔 ===== WEBHOOK EVENT RECEIVED =====")
        logger.info(f"🔔 Headers: {dict(request.headers)}")
        logger.info(f"🔔 Content-Type: {content_type}")
        logger.info(f"🔔 X-Adsk-Signature: {x_adsk_signature}")
        
        # Get raw request body for signature verification
        raw_body = await request.body()
        logger.info(f"🔔 Raw body length: {len(raw_body)} bytes")
        logger.info(f"🔔 Raw body preview: {raw_body[:500]}")
        
        # Parse JSON payload
        try:
            event_data = json.loads(raw_body)
            logger.info(f"🔔 Parsed event data: {json.dumps(event_data, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in webhook payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Log webhook event details - extract from correct webhook structure
        event_type = event_data.get('hook', {}).get('event', event_data.get('eventType', 'unknown'))
        resource_urn = event_data.get('resourceUrn', 'unknown')
        issue_id = event_data.get('payload', {}).get('id', event_data.get('issueId', 'unknown'))
        timestamp = event_data.get('timestamp', 'unknown')
        
        logger.info("🔔 ===== WEBHOOK EVENT DETAILS =====")
        logger.info(f"🔔 Event Type: {event_type}")
        logger.info(f"🔔 Resource URN: {resource_urn}")
        logger.info(f"🔔 Issue ID: {issue_id}")
        logger.info(f"🔔 Timestamp: {timestamp}")
        logger.info("🔔 ===== STARTING WEBHOOK PROCESSING =====")
        
        logger.info(f"Processing webhook event: {event_type} for resource: {resource_urn}")
        
        # Verify webhook signature if provided (security measure)
        if x_adsk_signature:
            # For now, log the signature - implement verification once we have the secret
            logger.info(f"Webhook signature provided: {x_adsk_signature}")
            # TODO: Implement signature verification with webhook secret
        
        # Process the webhook event
        processing_result = await acc_webhook_service.process_webhook_event(event_data)
        
        if processing_result.get('success', False):
            logger.info(f"✅ Successfully processed webhook event: {event_type}")
            logger.info("🔔 ===== WEBHOOK PROCESSING COMPLETE =====")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "Webhook event processed successfully",
                    "event_type": event_type,
                    "processing_result": processing_result
                }
            )
        else:
            logger.error(f"❌ Failed to process webhook event: {processing_result.get('message')}")
            logger.error("🔔 ===== WEBHOOK PROCESSING FAILED =====")
            return JSONResponse(
                status_code=status.HTTP_200_OK,  # Still return 200 to avoid retries
                content={
                    "status": "warning", 
                    "message": processing_result.get('message', 'Failed to process webhook event'),
                    "event_type": event_type,
                    "processing_result": processing_result
                }
            )
        
    except Exception as e:
        logger.error(f"Error processing webhook event: {e}")
        # Return 200 to avoid webhook retries for processing errors
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "error",
                "message": f"Internal processing error: {str(e)}"
            }
        )


@router.post("/challenge")
async def webhook_challenge(request: Request):
    """
    Handle webhook challenge/verification requests from Autodesk.
    
    When registering a webhook, Autodesk sends a challenge request
    that must be responded to correctly to verify the endpoint.
    """
    try:
        logger.info("Received webhook challenge request")
        
        # Get the challenge from the request
        try:
            challenge_data = await request.json()
        except json.JSONDecodeError:
            # If not JSON, try to get as text
            challenge_data = {"challenge": await request.body()}
        
        challenge = challenge_data.get('challenge')
        if challenge:
            logger.info(f"Responding to webhook challenge: {challenge}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"challenge": challenge}
            )
        else:
            logger.warning("No challenge found in webhook challenge request")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No challenge provided"
            )
        
    except Exception as e:
        logger.error(f"Error handling webhook challenge: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling webhook challenge: {str(e)}"
        )


@router.get("/status")
async def get_webhook_status():
    """
    Get the status of all registered webhooks.
    
    Returns information about active webhooks for debugging and monitoring.
    """
    try:
        logger.info("Getting webhook status")
        
        # Get status from webhook service
        all_status = {}
        for user_id in acc_webhook_service.active_webhooks.keys():
            user_status = acc_webhook_service.get_webhook_status(user_id)
            all_status[f"user_{user_id}"] = user_status
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "webhook_service_status": "active",
                "total_users": len(acc_webhook_service.active_webhooks),
                "supported_events": acc_webhook_service.supported_events,
                "user_webhooks": all_status
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting webhook status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting webhook status: {str(e)}"
        )


@router.post("/test")
async def test_webhook_endpoint(test_data: Dict[str, Any]):
    """
    Test webhook endpoint with sample data.
    
    Useful for testing webhook processing without waiting for real ACC events.
    """
    try:
        logger.info("🧪 ===== PROCESSING TEST WEBHOOK EVENT =====")
        
        # Add test event metadata using correct ACC issue event types
        test_event = {
            "eventType": "issue.created-1.0",
            "resourceUrn": "urn:adsk.wipprod:fs.file:test-project-123",
            "issueId": "test-issue-456",
            "timestamp": "2024-01-01T12:00:00Z",
            "source": "test",
            **test_data
        }
        
        logger.info(f"🧪 Test event data: {json.dumps(test_event, indent=2)}")
        
        # Process the test event
        processing_result = await acc_webhook_service.process_webhook_event(test_event)
        
        logger.info(f"🧪 Test processing result: {processing_result}")
        logger.info("🧪 ===== TEST WEBHOOK PROCESSING COMPLETE =====")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Test webhook event processed",
                "processing_result": processing_result,
                "test_event": test_event
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Error processing test webhook: {e}")
        import traceback
        logger.error(f"❌ Test webhook traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing test webhook: {str(e)}"
        )



@router.post("/test-real-issue")
async def test_real_issue_webhook():
    """
    Test webhook with realistic issue data that should trigger Slack notifications.
    
    This simulates a real issue creation that should trigger duplicate detection
    and information validation, then send Slack alerts.
    """
    try:
        logger.info("🧪 ===== TESTING REAL ISSUE WEBHOOK =====")
        
        # Create a realistic issue webhook event
        real_issue_event = {
            "eventType": "issue.created-1.0",
            "resourceUrn": "urn:adsk.wipprod:fs.file:a9d0e667-0611-44ea-ab8e-82b4884a8223",  # Use your real project ID
            "issueId": "test-issue-" + str(int(datetime.now().timestamp())),
            "timestamp": datetime.now().isoformat() + "Z",
            "userId": "test-user",
            "source": "test-real-issue",
            # Add issue attributes that will trigger validation
            "issueAttributes": {
                "title": "Test Issue - Material Problem",
                "description": "Short description",  # Incomplete - should trigger validation
                "status": "open",
                "priority": "high",  # Should trigger high priority alert
                "created": datetime.now().isoformat() + "Z"
            }
        }
        
        logger.info(f"🧪 Real issue event: {json.dumps(real_issue_event, indent=2)}")
        
        # Process the realistic event
        processing_result = await acc_webhook_service.process_webhook_event(real_issue_event)
        
        logger.info(f"🧪 Real issue processing result: {processing_result}")
        logger.info("🧪 ===== REAL ISSUE WEBHOOK TEST COMPLETE =====")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Real issue webhook test processed",
                "processing_result": processing_result,
                "test_event": real_issue_event,
                "expected_behavior": [
                    "Should trigger duplicate detection",
                    "Should trigger information validation (incomplete description)",
                    "Should trigger high priority alert",
                    "Should send Slack notifications for each alert type"
                ]
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Error processing real issue webhook test: {e}")
        import traceback
        logger.error(f"❌ Real issue webhook test traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing real issue webhook test: {str(e)}"
        )


@router.post("/test-issue-processing")
async def test_issue_processing():
    """
    Test the issue processing flow directly by simulating polling detection.
    
    This bypasses webhook registration and directly tests the issue detection and notification flow.
    """
    try:
        logger.info("🧪 ===== TESTING ISSUE PROCESSING FLOW =====")
        
        # Import the issue monitoring service
        from sqlalchemy import select

        from ..database import get_db
        from ..models import Connection, ConnectionStatus
        from ..services.acc_issue_monitoring_service import \
            issue_monitoring_service

        # Create a test issue that should trigger alerts
        test_issue_data = {
            "id": "test-issue-" + str(int(datetime.now().timestamp())),
            "type": "issues",
            "attributes": {
                "title": "Test Material Delivery Issue",
                "description": "Very short desc",  # Should trigger incomplete validation
                "status": "open",
                "priority": "high",  # Should trigger high priority alert
                "created": datetime.now().isoformat() + "Z",
                "updated": datetime.now().isoformat() + "Z"
            }
        }
        
        test_project_data = {
            "id": "a9d0e667-0611-44ea-ab8e-82b4884a8223",
            "type": "projects", 
            "attributes": {
                "name": "Test Construction Project"
            }
        }
        
        # Get user's ACC connection
        async with get_db() as db:
            result = await db.execute(
                select(Connection)
                .where(Connection.user_id == 1)  # Assuming user ID 1
                .where(Connection.platform == 'acc')
                .where(Connection.status == ConnectionStatus.ACTIVE)
            )
            connection = result.scalar_one_or_none()
            
            if not connection:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "No active ACC connection found for user 1"
                    }
                )
            
            logger.info(f"🧪 Using ACC connection: {connection.name}")
            logger.info(f"🧪 Test issue data: {json.dumps(test_issue_data, indent=2)}")
            
            # Directly call the issue processing method
            await issue_monitoring_service._process_new_issue(
                user_id=1,
                connection=connection,
                project_id=test_project_data["id"], 
                project_data=test_project_data,
                issue_data=test_issue_data,
                db=db
            )
            
        logger.info("🧪 ===== ISSUE PROCESSING TEST COMPLETE =====")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Issue processing flow test completed",
                "test_issue": test_issue_data,
                "test_project": test_project_data,
                "expected_behavior": [
                    "Should run duplicate detection",
                    "Should run information validation (should detect incomplete description)",
                    "Should run high priority escalation (priority=high)",
                    "Should trigger event bus events",
                    "Should send Slack notifications to acc-alerts channel"
                ]
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Error testing issue processing flow: {e}")
        import traceback
        logger.error(f"❌ Issue processing test traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error testing issue processing flow: {str(e)}"
        )
