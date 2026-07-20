"""Tests for src/services/file_management_service.py"""
import os
import tempfile
import pytest

class TestFileManagementService:
    @pytest.mark.asyncio
    async def test_file_management_initialization(self):
        from src.services.file_management_service import FileManagementService
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["FILE_UPLOAD_DIR"] = tmp_dir
            service = FileManagementService()
            assert service is not None

    @pytest.mark.asyncio
    async def test_upload_directory_creation(self):
        from src.services.file_management_service import FileManagementService
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["FILE_UPLOAD_DIR"] = tmp_dir
            service = FileManagementService()
            assert service.upload_dir is not None
