"""
Persistent Audit Store — PostgreSQL-backed audit chain storage.

Replaces InMemoryAuditStore with durable, queryable storage using
the existing SQLAlchemy async engine. Provides:
- ACID-compliant record persistence
- Automatic eviction with genesis hash rotation
- Query capabilities for observability dashboards
"""
import logging
from typing import Optional, Tuple, List
from datetime import datetime

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import get_session_maker
from src.models import AuditRecordRow, AuditChainMetaRow

logger = logging.getLogger(__name__)

MAX_AUDIT_RECORDS = 10_000


class PostgresAuditStore:
    """
    Persistent audit store backed by PostgreSQL.

    Implements the same interface as InMemoryAuditStore but stores
    records in the database for durability and queryability.

    Note: This store is designed for async usage. The RuntimeAuditLogger
    currently uses synchronous calls, so this store wraps async operations
    in a synchronous facade using the event loop.
    """

    def __init__(self, session_maker: Optional[async_sessionmaker] = None):
        self._session_maker = session_maker
        self._chain_genesis_hash: Optional[str] = None
        self._max_records = MAX_AUDIT_RECORDS

    def _get_session_maker(self) -> async_sessionmaker:
        if self._session_maker is None:
            self._session_maker = get_session_maker()
        return self._session_maker

    async def async_append(self, record) -> Optional[object]:
        """
        Append an audit record to the database.
        Returns the evicted record if the store is at capacity.
        """
        import json
        from src.core.runtime.immutability import _stable_json_repr

        session_maker = self._get_session_maker()
        async with session_maker() as session:
            async with session.begin():
                # Check capacity
                count_result = await session.execute(
                    select(func.count()).select_from(AuditRecordRow)
                )
                current_count = count_result.scalar() or 0

                evicted = None
                if current_count >= self._max_records:
                    # Evict oldest record
                    oldest = await session.execute(
                        select(AuditRecordRow).order_by(AuditRecordRow.id).limit(1)
                    )
                    oldest_row = oldest.scalar_one_or_none()
                    if oldest_row:
                        evicted = self._row_to_record(oldest_row)
                        await session.execute(
                            delete(AuditRecordRow).where(AuditRecordRow.id == oldest_row.id)
                        )

                # Serialize output
                output_json = None
                if record.output is not None:
                    try:
                        output_json = _stable_json_repr(record.output)
                    except Exception:
                        output_json = "{}"

                # Insert new record
                row = AuditRecordRow(
                    skill_name=record.skill_name,
                    tool_name=record.tool_name,
                    timestamp=record.timestamp,
                    execution_time_ms=record.execution_time_ms,
                    status=record.status.value,
                    governance_decision=record.governance_decision.value,
                    execution_id=str(record.execution_id),
                    runtime_version=record.runtime_version,
                    approved_by_human=record.approved_by_human,
                    environment=record.environment.value,
                    output_json=output_json,
                    record_hash=record.record_hash,
                    previous_record_hash=record.previous_record_hash,
                    error_message=record.error_message,
                )
                session.add(row)

                # Update metadata
                meta = await session.execute(
                    select(AuditChainMetaRow).where(AuditChainMetaRow.id == 1)
                )
                meta_row = meta.scalar_one_or_none()
                if meta_row:
                    meta_row.record_count = current_count + 1 - (1 if evicted else 0)
                    meta_row.last_updated = datetime.utcnow()
                else:
                    session.add(AuditChainMetaRow(
                        id=1,
                        genesis_hash=self._chain_genesis_hash,
                        record_count=1,
                        last_updated=datetime.utcnow(),
                    ))

            return evicted

    async def async_all(self) -> Tuple:
        """Get all audit records ordered by insertion."""
        session_maker = self._get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AuditRecordRow).order_by(AuditRecordRow.id)
            )
            rows = result.scalars().all()
            return tuple(self._row_to_record(row) for row in rows)

    async def async_get_chain_genesis_hash(self) -> Optional[str]:
        """Get the chain genesis hash from metadata."""
        session_maker = self._get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AuditChainMetaRow).where(AuditChainMetaRow.id == 1)
            )
            meta = result.scalar_one_or_none()
            return meta.genesis_hash if meta else None

    async def async_set_chain_genesis_hash(self, hash_value: Optional[str]) -> None:
        """Set the chain genesis hash in metadata."""
        session_maker = self._get_session_maker()
        async with session_maker() as session:
            async with session.begin():
                result = await session.execute(
                    select(AuditChainMetaRow).where(AuditChainMetaRow.id == 1)
                )
                meta = result.scalar_one_or_none()
                if meta:
                    meta.genesis_hash = hash_value
                else:
                    session.add(AuditChainMetaRow(
                        id=1, genesis_hash=hash_value, record_count=0,
                    ))
        self._chain_genesis_hash = hash_value

    async def async_query_by_skill(
        self, skill_name: str, limit: int = 100
    ) -> List:
        """Query records by skill name for observability."""
        session_maker = self._get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AuditRecordRow)
                .where(AuditRecordRow.skill_name == skill_name)
                .order_by(AuditRecordRow.id.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [self._row_to_record(row) for row in rows]

    async def async_query_by_status(
        self, status: str, limit: int = 100
    ) -> List:
        """Query records by status for error tracking."""
        session_maker = self._get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AuditRecordRow)
                .where(AuditRecordRow.status == status)
                .order_by(AuditRecordRow.id.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: AuditRecordRow):
        """Convert a database row to an ExecutionAuditRecord."""
        import json
        from uuid import UUID
        from src.core.runtime.audit import ExecutionAuditRecord
        from src.core.runtime.status import ExecutionStatus
        from src.core.runtime.governance import GovernanceDecision
        from src.core.skills.models import EnvironmentScope
        from src.core.runtime.immutability import freeze_structure

        output = None
        if row.output_json:
            try:
                raw = json.loads(row.output_json)
                output = freeze_structure(raw)
            except Exception:
                output = None

        return ExecutionAuditRecord(
            skill_name=row.skill_name,
            tool_name=row.tool_name,
            timestamp=row.timestamp,
            execution_time_ms=row.execution_time_ms,
            status=ExecutionStatus(row.status),
            governance_decision=GovernanceDecision(row.governance_decision),
            execution_id=UUID(row.execution_id),
            runtime_version=row.runtime_version,
            approved_by_human=row.approved_by_human,
            environment=EnvironmentScope(row.environment),
            output=output,
            record_hash=row.record_hash,
            previous_record_hash=row.previous_record_hash,
            error_message=row.error_message,
        )
