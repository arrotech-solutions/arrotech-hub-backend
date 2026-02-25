"""
Pytest configuration and fixtures for Mini-Hub tests.
Standalone test suite with in-memory SQLite database.
"""
import asyncio
import os
import warnings
from datetime import datetime, timedelta
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Set test environment BEFORE any imports from src
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-12345678"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-12345678"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["REDIS_URL"] = ""
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_fake"

# Suppress deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Local application imports (after environment setup)
from src.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.models import (  # noqa: E402
    Connection,
    Conversation,
    User,
    UserSettings,
    Workflow,
    WorkflowStep,
)

# Password hashing function
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


# JWT token creation - must match auth_router.py
JWT_SECRET_KEY = "your-secret-key-here"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def create_access_token(data: dict) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# Test database URL (async SQLite in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """Create async test engine with in-memory SQLite."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a new database session for each test."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(
    db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with database override."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Always mock rate_limit_service to prevent 429s in tests.
    # The real one may be set during app startup, so we override unconditionally.
    from unittest.mock import AsyncMock, MagicMock
    mock_rate_limit = MagicMock()
    mock_rate_limit.check_limit = AsyncMock(return_value=True)
    app.state.rate_limit_service = mock_rate_limit

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    """Test user registration data."""
    return {
        "email": "test@example.com",
        "password": "TestPassword123!",
        "name": "Test User"
    }


@pytest.fixture
def test_user_data_2():
    """Second test user data."""
    return {
        "email": "test2@example.com",
        "password": "TestPassword456!",
        "name": "Test User 2"
    }


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_user_data) -> User:
    """Create a test user in the database."""
    user = User(
        email=test_user_data["email"],
        name=test_user_data["name"],
        password_hash=get_password_hash(test_user_data["password"]),
        subscription_tier="free"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user_2(db_session: AsyncSession, test_user_data_2) -> User:
    """Create a second test user in the database."""
    user = User(
        email=test_user_data_2["email"],
        name=test_user_data_2["name"],
        password_hash=get_password_hash(test_user_data_2["password"]),
        subscription_tier="free"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_token(test_user: User) -> str:
    """Get authentication token for test user."""
    return create_access_token(data={"sub": test_user.email})


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    """Get authentication headers for testing."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def auth_token_2(test_user_2: User) -> str:
    """Get authentication token for second test user."""
    return create_access_token(data={"sub": test_user_2.email})


@pytest_asyncio.fixture
async def auth_headers_2(auth_token_2: str) -> dict:
    """Get authentication headers for second test user."""
    return {"Authorization": f"Bearer {auth_token_2}"}


@pytest_asyncio.fixture
async def test_user_settings(
    db_session: AsyncSession, test_user: User
) -> UserSettings:
    """Create test user settings."""
    settings = UserSettings(
        user_id=test_user.id,
        email_notifications=True,
        slack_notifications=False,
        webhook_notifications=False,
        dashboard_theme="light",
        dashboard_layout="default",
        api_rate_limit=1000,
        api_timeout=30,
    )
    db_session.add(settings)
    await db_session.commit()
    await db_session.refresh(settings)
    return settings


@pytest_asyncio.fixture
async def test_workflow(
    db_session: AsyncSession, test_user: User
) -> Workflow:
    """Create a test workflow."""
    workflow = Workflow(
        user_id=test_user.id,
        name="Test Workflow",
        description="A test workflow for testing",
        status="draft",
        trigger_type="manual",
    )
    db_session.add(workflow)
    await db_session.commit()
    await db_session.refresh(workflow)
    return workflow


@pytest_asyncio.fixture
async def test_workflow_with_steps(
    db_session: AsyncSession, test_user: User
) -> Workflow:
    """Create a test workflow with steps."""
    workflow = Workflow(
        user_id=test_user.id,
        name="Test Workflow With Steps",
        description="A test workflow with steps",
        status="draft",
        trigger_type="manual",
    )
    db_session.add(workflow)
    await db_session.commit()
    await db_session.refresh(workflow)

    # Add steps
    step1 = WorkflowStep(
        workflow_id=workflow.id,
        step_number=1,
        tool_name="test_tool",
        tool_parameters={"param1": "value1"},
        description="First step",
    )
    step2 = WorkflowStep(
        workflow_id=workflow.id,
        step_number=2,
        tool_name="test_tool_2",
        tool_parameters={"param2": "value2"},
        description="Second step",
    )
    db_session.add_all([step1, step2])
    await db_session.commit()
    await db_session.refresh(workflow)

    return workflow


@pytest_asyncio.fixture
async def test_connection(
    db_session: AsyncSession, test_user: User
) -> Connection:
    """Create a test connection."""
    connection = Connection(
        user_id=test_user.id,
        platform="hubspot",
        name="Test HubSpot Connection",
        config={"api_key": "test-api-key"},
        status="active",
    )
    db_session.add(connection)
    await db_session.commit()
    await db_session.refresh(connection)
    return connection


@pytest_asyncio.fixture
async def test_conversation(
    db_session: AsyncSession, test_user: User
) -> Conversation:
    """Create a test conversation."""
    conversation = Conversation(
        user_id=test_user.id,
        title="Test Conversation",
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


@pytest.fixture
def workflow_create_data():
    """Data for creating a workflow."""
    return {
        "workflow_name": "New Test Workflow",
        "description": "A newly created workflow for testing",
        "steps": [
            {
                "step_number": 1,
                "tool_name": "test_tool",
                "tool_parameters": {"param": "value"},
                "description": "Test step"
            }
        ],
        "trigger_type": "manual"
    }


@pytest.fixture
def settings_update_data():
    """Data for updating settings."""
    return {
        "notification_settings": {
            "email_notifications": True,
            "slack_notifications": True,
            "webhook_notifications": False,
            "notification_webhook_url": None
        },
        "api_settings": {
            "api_rate_limit": 500,
            "api_timeout": 60,
            "auto_refresh_tokens": True
        },
        "dashboard_settings": {
            "dashboard_theme": "dark",
            "dashboard_layout": "compact",
            "show_analytics": True,
            "show_usage_stats": True
        }
    }
