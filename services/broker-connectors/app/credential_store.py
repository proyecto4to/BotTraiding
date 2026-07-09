"""Credential storage abstraction (Fase 3).

Broker API keys/secrets must never be logged or returned in API responses.
``InMemoryCredentialStore`` is the Fase 3 implementation (per-process,
lost on restart); swapping in a real encrypted/vault-backed store later is
a one-function change: implement ``CredentialStore`` against
Vault/KMS/DB-encrypted columns and wire it in ``app/main.py`` instead of
``InMemoryCredentialStore()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BrokerCredentials:
    broker: str
    account_id: str = "default"
    api_key: str = ""
    api_secret: str = ""
    demo: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # never leak secrets via logs/repr
        return (
            f"BrokerCredentials(broker={self.broker!r}, account_id={self.account_id!r}, "
            f"demo={self.demo}, api_key='***', api_secret='***')"
        )

    __str__ = __repr__


class CredentialStore(ABC):
    """Interface a real vault/DB-encrypted implementation must satisfy."""

    @abstractmethod
    def save(self, credentials: BrokerCredentials) -> None: ...

    @abstractmethod
    def get(self, broker: str, account_id: str = "default") -> Optional[BrokerCredentials]: ...

    @abstractmethod
    def delete(self, broker: str, account_id: str = "default") -> None: ...


class InMemoryCredentialStore(CredentialStore):
    """Fase 3 in-memory implementation. Not persisted, not encrypted -
    acceptable only because this is scaffolding; real credentials must go
    through a Vault/KMS-backed store before any live trading."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], BrokerCredentials] = {}

    def save(self, credentials: BrokerCredentials) -> None:
        self._data[(credentials.broker, credentials.account_id)] = credentials

    def get(self, broker: str, account_id: str = "default") -> Optional[BrokerCredentials]:
        return self._data.get((broker, account_id))

    def delete(self, broker: str, account_id: str = "default") -> None:
        self._data.pop((broker, account_id), None)
