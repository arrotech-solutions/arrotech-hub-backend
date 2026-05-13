from typing import Tuple, Protocol, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .audit import ExecutionAuditRecord

class AuditStore(Protocol):
    def append(self, record: 'ExecutionAuditRecord') -> Optional['ExecutionAuditRecord']:
        ...

    def all(self) -> Tuple['ExecutionAuditRecord', ...]:
        ...

    def clear(self) -> None:
        ...

    def get_chain_genesis_hash(self) -> Optional[str]:
        ...

    def set_chain_genesis_hash(self, hash: Optional[str]) -> None:
        ...

import threading

MAX_AUDIT_RECORDS = 10000

class InMemoryAuditStore:
    def __init__(self):
        self._records = []
        self._genesis_hash = None
        self._lock = threading.Lock()

    def append(self, record: 'ExecutionAuditRecord') -> Optional['ExecutionAuditRecord']:
        with self._lock:
            evicted = None
            self._records.append(record)
            if len(self._records) > MAX_AUDIT_RECORDS:
                evicted = self._records.pop(0)
            return evicted

    def all(self) -> Tuple['ExecutionAuditRecord', ...]:
        with self._lock:
            return tuple(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._genesis_hash = None

    def get_chain_genesis_hash(self) -> Optional[str]:
        with self._lock:
            return self._genesis_hash

    def set_chain_genesis_hash(self, hash: Optional[str]) -> None:
        with self._lock:
            self._genesis_hash = hash
