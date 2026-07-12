"""Credential storage abstraction (Fase 3 + P1).

Broker API keys/secrets must never be logged or returned in API responses.
Two implementations satisfy ``CredentialStore``:

- ``InMemoryCredentialStore`` (Fase 3): per-process, lost on restart, not
  encrypted. Still the default (``CREDENTIAL_STORE=memory``) so existing
  behaviour/tests are unchanged.
- ``EncryptedDbCredentialStore`` (P1): Fernet-encrypted rows in Postgres/
  SQLite. Selected with ``CREDENTIAL_STORE=db`` + a ``BROKER_CRED_KEY``.
  Secrets are encrypted at rest and re-encryptable via key rotation.

``build_credential_store()`` picks the implementation from the environment.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


# --- P1: encrypted, persistent store ----------------------------------------


class CredentialKeyError(RuntimeError):
    """BROKER_CRED_KEY missing/invalid when the db store is selected."""


def make_fernet(key: str):
    """Build a Fernet from a urlsafe-base64 32-byte key.

    Generate one with:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    from cryptography.fernet import Fernet

    if not key:
        raise CredentialKeyError(
            "BROKER_CRED_KEY is required for CREDENTIAL_STORE=db (generate with "
            "cryptography.fernet.Fernet.generate_key())"
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # invalid length/base64
        raise CredentialKeyError(f"invalid BROKER_CRED_KEY: {exc}") from exc


class EncryptedDbCredentialStore(CredentialStore):
    """DB-backed store with Fernet-encrypted secrets.

    The api_key/api_secret/extra are encrypted into a single blob column; the
    key never leaves the process and the plaintext never hits the database.
    Rotating the key re-encrypts every row under a new key.
    """

    def __init__(self, session_factory, fernet) -> None:
        self._session_factory = session_factory
        self._fernet = fernet

    def _encrypt(self, credentials: BrokerCredentials) -> str:
        payload = json.dumps(
            {
                "api_key": credentials.api_key,
                "api_secret": credentials.api_secret,
                "extra": credentials.extra,
            }
        )
        return self._fernet.encrypt(payload.encode()).decode()

    def _decrypt(self, blob: str) -> dict:
        return json.loads(self._fernet.decrypt(blob.encode()).decode())

    def save(self, credentials: BrokerCredentials) -> None:
        from app.models import BrokerCredentialRow

        blob = self._encrypt(credentials)
        with self._session_factory() as session:
            row = (
                session.query(BrokerCredentialRow)
                .filter_by(broker=credentials.broker, account_id=credentials.account_id)
                .one_or_none()
            )
            if row is None:
                row = BrokerCredentialRow(
                    broker=credentials.broker,
                    account_id=credentials.account_id,
                    encrypted_blob=blob,
                    demo=credentials.demo,
                )
                session.add(row)
            else:
                row.encrypted_blob = blob
                row.demo = credentials.demo
                row.rotated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()

    def get(self, broker: str, account_id: str = "default") -> Optional[BrokerCredentials]:
        from app.models import BrokerCredentialRow

        with self._session_factory() as session:
            row = (
                session.query(BrokerCredentialRow)
                .filter_by(broker=broker, account_id=account_id)
                .one_or_none()
            )
            if row is None:
                return None
            data = self._decrypt(row.encrypted_blob)
            return BrokerCredentials(
                broker=broker,
                account_id=account_id,
                api_key=data.get("api_key", ""),
                api_secret=data.get("api_secret", ""),
                demo=row.demo,
                extra=data.get("extra", {}) or {},
            )

    def delete(self, broker: str, account_id: str = "default") -> None:
        from app.models import BrokerCredentialRow

        with self._session_factory() as session:
            session.query(BrokerCredentialRow).filter_by(
                broker=broker, account_id=account_id
            ).delete()
            session.commit()

    def rotate(self, new_key: str) -> int:
        """Re-encrypt every stored credential under a new Fernet key.

        Decrypts with the current key and re-encrypts with the new one inside
        a single transaction; afterwards the store uses the new key. Returns
        the number of rows re-encrypted. The old key can no longer decrypt the
        rows once this completes."""
        from app.models import BrokerCredentialRow

        new_fernet = make_fernet(new_key)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._session_factory() as session:
            rows = session.query(BrokerCredentialRow).all()
            for row in rows:
                plaintext = self._fernet.decrypt(row.encrypted_blob.encode())
                row.encrypted_blob = new_fernet.encrypt(plaintext).decode()
                row.rotated_at = now
            session.commit()
            count = len(rows)
        self._fernet = new_fernet
        return count


def build_credential_store() -> CredentialStore:
    """Pick the store from the environment.

    CREDENTIAL_STORE=memory (default) -> in-memory (Fase 3 behaviour).
    CREDENTIAL_STORE=db -> EncryptedDbCredentialStore (requires BROKER_CRED_KEY);
    the credential table is created for SQLite dev and migrated by Alembic in
    Postgres.
    """
    backend = os.environ.get("CREDENTIAL_STORE", "memory").lower()
    if backend != "db":
        return InMemoryCredentialStore()

    # Fail fast on a missing/invalid key before importing the DB layer.
    fernet = make_fernet(os.environ.get("BROKER_CRED_KEY", ""))

    from app import db as db_module

    if db_module.DATABASE_URL.startswith("sqlite"):
        db_module.create_all()
    return EncryptedDbCredentialStore(db_module.SessionLocal, fernet)
