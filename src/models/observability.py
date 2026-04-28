"""
Observability models for logs, traces, and dead letter queue.
"""
import uuid
from enum import Enum
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func
from ..database import Base

class ErrorType(str, Enum):
    USER_ERROR = "USER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    UNKNOWN = "UNKNOWN"

class ObservabilityLog(Base):
    """Structured JSON logs persisted to database."""
    __tablename__ = "observability_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    level = Column(String, nullable=False)
    trace_id = Column(String, index=True, nullable=True)
    span_id = Column(String, index=True, nullable=True)
    event_type = Column(String, index=True, nullable=False)
    
    # Context
    customer_id = Column(String, index=True, nullable=True)
    agent_id = Column(String, index=True, nullable=True)
    workflow_id = Column(String, index=True, nullable=True)
    tool_name = Column(String, index=True, nullable=True)
    step_name = Column(String, nullable=True)
    
    # Status & Timing
    status = Column(String, index=True, nullable=True) # success, failed, pending
    duration_ms = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Data
    payload = Column(JSON, nullable=True) # Contains input, output, and extra metadata
    
    # Error info
    error_type = Column(String, index=True, nullable=True)
    error_message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)

class ObservabilityTrace(Base):
    """High-level trace summaries for easier querying."""
    __tablename__ = "observability_traces"

    trace_id = Column(String, primary_key=True)
    root_event = Column(String, nullable=False)
    customer_id = Column(String, index=True, nullable=True)
    status = Column(String, default="pending")
    total_duration_ms = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FailedEvent(Base):
    """Dead Letter Queue (DLQ) for retrying failed webhooks or tool calls."""
    __tablename__ = "failed_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String, index=True, nullable=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    status = Column(String, default="failed", index=True) # failed, retrying, recovered, abandoned
    last_attempt_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_failed_events_status_retry', 'status', 'retry_count'),
    )
