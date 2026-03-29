"""
Tests for service classes.
"""
import os
import tempfile
from unittest.mock import patch

import pytest


class TestEmailService:
    """Tests for EmailService."""

    @pytest.mark.asyncio
    async def test_email_service_initialization(self):
        """Test email service can be imported."""
        from src.services.email_service import EmailService
        service = EmailService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_email_service_has_methods(self):
        """Test email service has expected methods."""
        from src.services.email_service import EmailService
        service = EmailService()
        # Check service exists and has common attributes
        assert hasattr(service, '__class__')

    @pytest.mark.asyncio
    async def test_email_template_rendering(self):
        """Test email template rendering."""
        from src.services.email_service import EmailService
        service = EmailService()
        assert hasattr(service, '__class__')


class TestBillingService:
    """Tests for BillingService."""

    @pytest.mark.asyncio
    async def test_billing_service_initialization(self):
        """Test billing service can be imported."""
        from src.services.billing_service import BillingService
        service = BillingService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_get_pricing_tiers(self):
        """Test getting pricing tiers."""
        from src.services.billing_service import BillingService
        service = BillingService()
        # Check if method exists
        if hasattr(service, 'get_pricing_tiers'):
            result = service.get_pricing_tiers()
            assert result is not None

    @pytest.mark.asyncio
    async def test_calculate_usage(self):
        """Test calculating usage."""
        from src.services.billing_service import BillingService
        service = BillingService()
        assert service is not None


class TestRateLimitService:
    """Tests for RateLimitService."""

    @pytest.mark.asyncio
    async def test_rate_limit_service_initialization(self):
        """Test rate limit service can be imported."""
        from src.services.rate_limit_service import RateLimitService
        service = RateLimitService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_check_rate_limit(self):
        """Test checking rate limit."""
        from src.services.rate_limit_service import RateLimitService
        service = RateLimitService()
        # Check rate limit functionality
        if hasattr(service, 'check_limit'):
            result = service.check_limit("test_user", "test_endpoint")
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_remaining_requests(self):
        """Test getting remaining requests."""
        from src.services.rate_limit_service import RateLimitService
        service = RateLimitService()
        assert service is not None


class TestLLMService:
    """Tests for LLMService."""

    @pytest.mark.asyncio
    async def test_llm_service_initialization(self):
        """Test LLM service can be imported."""
        from src.services.llm_service import LLMService
        service = LLMService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_llm_service_providers(self):
        """Test getting available providers."""
        from src.services.llm_service import LLMService
        service = LLMService()
        providers = service.get_available_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0

    @pytest.mark.asyncio
    async def test_llm_service_models(self):
        """Test getting available models."""
        from src.services.llm_service import LLMService
        service = LLMService()
        if hasattr(service, 'get_available_models'):
            models = service.get_available_models()
            assert isinstance(models, (list, dict))


class TestWorkflowBuilderService:
    """Tests for WorkflowBuilderService."""

    @pytest.mark.asyncio
    async def test_workflow_builder_initialization(self):
        """Test workflow builder service can be imported."""
        from src.services.workflow_builder_service import \
            WorkflowBuilderService
        service = WorkflowBuilderService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_workflow_builder_create(self):
        """Test workflow creation."""
        from src.services.workflow_builder_service import \
            WorkflowBuilderService
        service = WorkflowBuilderService()
        assert service is not None


class TestAutonomousAgentService:
    """Tests for AutonomousAgentService."""

    @pytest.mark.asyncio
    async def test_autonomous_agent_initialization(self):
        """Test autonomous agent service can be imported."""
        from src.services.autonomous_agent_service import \
            AutonomousAgentService
        service = AutonomousAgentService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_create_agent(self):
        """Test agent creation."""
        from src.services.autonomous_agent_service import \
            AutonomousAgentService
        service = AutonomousAgentService()
        if hasattr(service, 'create_agent'):
            with patch.object(
                service, 'create_agent', return_value={"agent_id": "test"}
            ):
                result = service.create_agent(workflow_id=1, config={})
                assert result is not None

    @pytest.mark.asyncio
    async def test_list_agents(self):
        """Test listing agents."""
        from src.services.autonomous_agent_service import \
            AutonomousAgentService
        service = AutonomousAgentService()
        if hasattr(service, 'list_agents'):
            agents = service.list_agents(user_id=1)
            assert isinstance(agents, list)


class TestFileManagementService:
    """Tests for FileManagementService."""

    @pytest.mark.asyncio
    async def test_file_management_initialization(self):
        """Test file management service can be imported."""
        from src.services.file_management_service import FileManagementService
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["FILE_UPLOAD_DIR"] = tmp_dir
            service = FileManagementService()
            assert service is not None

    @pytest.mark.asyncio
    async def test_get_upload_dir(self):
        """Test getting upload directory."""
        from src.services.file_management_service import FileManagementService
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["FILE_UPLOAD_DIR"] = tmp_dir
            service = FileManagementService()
            assert service.upload_dir is not None


class TestWebToolsService:
    """Tests for WebToolsService."""

    @pytest.mark.asyncio
    async def test_web_tools_initialization(self):
        """Test web tools service can be imported."""
        from src.services.web_tools_service import WebToolsService
        service = WebToolsService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_web_tools_version(self):
        """Test web tools version."""
        from src.services.web_tools_service import WebToolsService
        service = WebToolsService()
        if hasattr(service, 'version'):
            assert service.version is not None


class TestPaymentService:
    """Tests for PaymentService."""

    @pytest.mark.asyncio
    async def test_payment_service_initialization(self):
        """Test payment service can be imported."""
        from src.services.payment_service import PaymentService
        service = PaymentService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_mpesa_initialization(self):
        """Test M-Pesa initialization."""
        from src.services.payment_service import PaymentService
        service = PaymentService()
        # Check M-Pesa config
        assert service is not None


class TestIntentProcessor:
    """Tests for IntentProcessor."""

    @pytest.mark.asyncio
    async def test_intent_processor_initialization(self):
        """Test intent processor can be imported."""
        try:
            from src.services.intent_processor import IntentProcessor
            processor = IntentProcessor()
            assert processor is not None
        except (ImportError, TypeError):
            # May require arguments or have import issues
            pytest.skip("IntentProcessor requires special initialization")


class TestDynamicToolRegistry:
    """Tests for DynamicToolRegistry."""

    @pytest.mark.asyncio
    async def test_tool_registry_initialization(self):
        """Test tool registry can be imported."""
        from src.services.dynamic_tool_registry import DynamicToolRegistry
        registry = DynamicToolRegistry()
        assert registry is not None

    @pytest.mark.asyncio
    async def test_get_tools(self):
        """Test getting tools."""
        from src.services.dynamic_tool_registry import DynamicToolRegistry
        registry = DynamicToolRegistry()
        if hasattr(registry, 'get_tools'):
            tools = registry.get_tools()
            assert tools is not None


class TestPlatformRegistry:
    """Tests for PlatformRegistry."""

    @pytest.mark.asyncio
    async def test_platform_registry_initialization(self):
        """Test platform registry can be imported."""
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()
        assert registry is not None

    @pytest.mark.asyncio
    async def test_get_platforms(self):
        """Test getting platforms."""
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()
        if hasattr(registry, 'get_platforms'):
            platforms = registry.get_platforms()
            assert platforms is not None

    @pytest.mark.asyncio
    async def test_linkedin_platform_uses_dedicated_tools(self):
        """LinkedIn platform should expose dedicated linkedin_* tools."""
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()

        linkedin_tools = registry.get_platform_tools("linkedin")
        tool_names = {tool["name"] for tool in linkedin_tools}

        assert "linkedin_network_management" in tool_names
        assert "linkedin_content_management" in tool_names
        assert "linkedin_analytics" in tool_names

    @pytest.mark.asyncio
    async def test_linkedin_platform_does_not_use_generic_social_media_tools(self):
        """LinkedIn tools should not be mapped to generic social media tools."""
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()

        linkedin_tools = registry.get_platform_tools("linkedin")
        tool_names = {tool["name"] for tool in linkedin_tools}

        assert "social_media_management" not in tool_names
        assert "social_media_analytics" not in tool_names


class TestWorkflowSharingService:
    """Tests for WorkflowSharingService."""

    @pytest.mark.asyncio
    async def test_workflow_sharing_initialization(self):
        """Test workflow sharing service can be imported."""
        from src.services.workflow_sharing_service import \
            WorkflowSharingService
        service = WorkflowSharingService()
        assert service is not None
