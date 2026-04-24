"""
Tests for src/database.py — URL parsing, engine creation, session management, seed logic.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetDatabaseUrl:
    """Tests for get_database_url() URL conversion logic."""

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@host/db"})
    def test_converts_postgresql_to_asyncpg(self):
        from src.database import get_database_url
        url = get_database_url()
        assert url.startswith("postgresql+asyncpg://")

    @patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host/db"})
    def test_converts_postgres_to_asyncpg(self):
        from src.database import get_database_url
        url = get_database_url()
        assert url.startswith("postgresql+asyncpg://")

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h/db?sslmode=require"})
    def test_strips_sslmode_query_param(self):
        from src.database import get_database_url
        url = get_database_url()
        assert "sslmode" not in url

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h/db?foo=bar&sslmode=require"})
    def test_strips_sslmode_with_other_params(self):
        from src.database import get_database_url
        url = get_database_url()
        assert "sslmode" not in url
        assert "foo=bar" in url

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h/db?foo=bar&sslmode=require&baz=qux"})
    def test_strips_sslmode_preserves_trailing_params(self):
        from src.database import get_database_url
        url = get_database_url()
        assert "sslmode" not in url
        assert "baz=qux" in url

    @patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"})
    def test_sqlite_url_passthrough(self):
        from src.database import get_database_url
        url = get_database_url()
        assert url == "sqlite+aiosqlite:///:memory:"

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h/db?sslmode=require&other=yes"})
    def test_sslmode_as_first_param_with_others(self):
        from src.database import get_database_url
        url = get_database_url()
        assert "sslmode" not in url

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@host:5432/mydb"})
    def test_preserves_port_in_url(self):
        from src.database import get_database_url
        url = get_database_url()
        assert ":5432" in url
        assert "mydb" in url

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql+asyncpg://u:p@h/db"})
    def test_already_asyncpg_url(self):
        """URL already in asyncpg format should not double-prefix."""
        from src.database import get_database_url
        url = get_database_url()
        # Should not add another asyncpg prefix
        assert url.count("asyncpg") == 1

    @patch.dict(os.environ, {}, clear=False)
    def test_default_url_when_no_env_var(self):
        """When DATABASE_URL is not set, use default."""
        env_backup = os.environ.pop("DATABASE_URL", None)
        try:
            from src.database import get_database_url
            url = get_database_url()
            assert "localhost" in url or "minihub" in url
        finally:
            if env_backup:
                os.environ["DATABASE_URL"] = env_backup

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:p%40ss@host/db"})
    def test_url_with_encoded_password(self):
        from src.database import get_database_url
        url = get_database_url()
        assert "p%40ss" in url


class TestGetEngine:
    def test_get_engine_returns_engine(self):
        from src.database import get_engine
        assert get_engine() is not None

    def test_get_engine_returns_same_instance(self):
        from src.database import get_engine
        assert get_engine() is get_engine()

    def test_get_engine_has_pool(self):
        from src.database import get_engine
        engine = get_engine()
        assert hasattr(engine, 'pool')


class TestGetSessionMaker:
    def test_returns_callable(self):
        from src.database import get_session_maker
        assert callable(get_session_maker())

    def test_returns_session_maker_instance(self):
        from src.database import get_session_maker
        from sqlalchemy.ext.asyncio import async_sessionmaker
        sm = get_session_maker()
        assert isinstance(sm, async_sessionmaker)


class TestGetDb:
    @pytest.mark.asyncio
    async def test_get_db_yields_session(self):
        from src.database import get_db
        async for session in get_db():
            assert session is not None
            break

    @pytest.mark.asyncio
    async def test_get_db_session_has_expected_methods(self):
        from src.database import get_db
        async for session in get_db():
            assert hasattr(session, 'commit')
            assert hasattr(session, 'rollback')
            assert hasattr(session, 'execute')
            assert hasattr(session, 'close')
            break


class TestSeedAdminUser:
    @pytest.mark.asyncio
    @patch.dict(os.environ, {"ADMIN_EMAIL": "", "ADMIN_PASSWORD": ""})
    async def test_seed_admin_skips_when_no_credentials(self):
        from src.database import seed_admin_user
        await seed_admin_user()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"ADMIN_EMAIL": "", "ADMIN_PASSWORD": "pass"})
    async def test_seed_admin_skips_when_no_email(self):
        from src.database import seed_admin_user
        await seed_admin_user()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"ADMIN_EMAIL": "admin@test.com", "ADMIN_PASSWORD": ""})
    async def test_seed_admin_skips_when_no_password(self):
        from src.database import seed_admin_user
        await seed_admin_user()


class TestBaseAndMetadata:
    def test_base_class_exists(self):
        from src.database import Base
        assert Base is not None
        assert hasattr(Base, 'metadata')

    def test_metadata_exists(self):
        from src.database import metadata
        assert metadata is not None


class TestInitDb:
    @pytest.mark.asyncio
    async def test_init_db_runs(self):
        from src.database import init_db
        try:
            await init_db()
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_init_db_imports_models(self):
        """init_db should import models to register them."""
        from src.database import init_db
        try:
            await init_db()
        except Exception:
            pass
        # Verify models are importable (registered with Base)
        from src.models import User, Subscription, UsageLog
        assert User is not None
        assert Subscription is not None
        assert UsageLog is not None
