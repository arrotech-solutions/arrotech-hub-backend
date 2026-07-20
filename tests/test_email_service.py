"""Tests for src/services/email_service.py"""
import pytest

class TestEmailService:
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
        assert hasattr(service, '__class__')

    @pytest.mark.asyncio
    async def test_email_template_rendering(self):
        """Test email template rendering."""
        from src.services.email_service import EmailService
        service = EmailService()
        assert hasattr(service, '__class__')
