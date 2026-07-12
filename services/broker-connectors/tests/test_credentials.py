"""P1 — encrypted, persistent broker credentials.

- round-trip: save then get returns the same secrets;
- at rest the api_secret never appears in the row (it is Fernet-encrypted);
- the db store refuses to build without a key; memory stays the default;
- key rotation re-encrypts every row and invalidates the old key;
- secrets never appear in reprs or in the connect/status API response shapes;
- the rotation endpoint is admin-only and rejects the memory backend.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.credential_store import (
    BrokerCredentials,
    CredentialKeyError,
    EncryptedDbCredentialStore,
    InMemoryCredentialStore,
    build_credential_store,
    make_fernet,
)
from app.main import ConnectResponse, StatusResponse, app
from app.models import Base, BrokerCredentialRow


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db_store(session_factory):
    return EncryptedDbCredentialStore(session_factory, Fernet(Fernet.generate_key()))


def _creds(secret="s3cr3t-key-value"):
    return BrokerCredentials(
        broker="binance",
        account_id="acct-1",
        api_key="pubkey-123",
        api_secret=secret,
        demo=True,
        extra={"quote_asset": "USDT"},
    )


def test_encrypt_roundtrip(db_store):
    db_store.save(_creds())
    loaded = db_store.get("binance", "acct-1")

    assert loaded is not None
    assert loaded.api_key == "pubkey-123"
    assert loaded.api_secret == "s3cr3t-key-value"
    assert loaded.demo is True
    assert loaded.extra == {"quote_asset": "USDT"}
    assert db_store.get("binance", "missing") is None


def test_secret_is_encrypted_at_rest(db_store, session_factory):
    db_store.save(_creds(secret="TOP-SECRET-XYZ"))
    with session_factory() as session:
        row = session.query(BrokerCredentialRow).one()
    assert "TOP-SECRET-XYZ" not in row.encrypted_blob
    assert "pubkey-123" not in row.encrypted_blob  # api_key is in the blob too


def test_save_is_upsert(db_store, session_factory):
    db_store.save(_creds(secret="first"))
    db_store.save(_creds(secret="second"))
    with session_factory() as session:
        assert session.query(BrokerCredentialRow).count() == 1
    assert db_store.get("binance", "acct-1").api_secret == "second"


def test_delete(db_store):
    db_store.save(_creds())
    db_store.delete("binance", "acct-1")
    assert db_store.get("binance", "acct-1") is None


def test_make_fernet_requires_a_key():
    with pytest.raises(CredentialKeyError):
        make_fernet("")
    with pytest.raises(CredentialKeyError):
        make_fernet("not-a-valid-fernet-key")


def test_factory_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_STORE", raising=False)
    assert isinstance(build_credential_store(), InMemoryCredentialStore)


def test_factory_db_backend_refuses_without_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_STORE", "db")
    monkeypatch.delenv("BROKER_CRED_KEY", raising=False)
    with pytest.raises(CredentialKeyError):
        build_credential_store()


def test_rotation_reencrypts_and_invalidates_old_key(db_store, session_factory):
    db_store.save(_creds(secret="rotate-me"))
    with session_factory() as session:
        old_blob = session.query(BrokerCredentialRow).one().encrypted_blob
    old_fernet = db_store._fernet  # capture before rotation

    new_key = Fernet.generate_key().decode()
    count = db_store.rotate(new_key)

    assert count == 1
    # Still readable through the store (now using the new key).
    assert db_store.get("binance", "acct-1").api_secret == "rotate-me"
    # The blob changed and the old key can no longer decrypt it.
    with session_factory() as session:
        new_blob = session.query(BrokerCredentialRow).one().encrypted_blob
    assert new_blob != old_blob
    with pytest.raises(InvalidToken):
        old_fernet.decrypt(new_blob.encode())


def test_repr_and_response_shapes_hide_secrets():
    text = repr(_creds(secret="must-not-appear"))
    assert "must-not-appear" not in text
    assert "***" in text
    # The API response models structurally cannot carry secrets.
    assert "api_key" not in ConnectResponse.model_fields
    assert "api_secret" not in ConnectResponse.model_fields
    assert "api_secret" not in StatusResponse.model_fields


# --- rotation endpoint -------------------------------------------------------


def _admin_token(roles=("admin",)):
    payload = {
        "sub": str(uuid.uuid4()),
        "roles": list(roles),
        "type": "access",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.fixture()
def client():
    return TestClient(app)


def test_rotate_endpoint_requires_admin(client):
    body = {"new_key": Fernet.generate_key().decode()}
    assert client.post("/connectors/credentials/rotate", json=body).status_code == 401
    forbidden = client.post(
        "/connectors/credentials/rotate",
        json=body,
        headers={"Authorization": f"Bearer {_admin_token(roles=['trader'])}"},
    )
    assert forbidden.status_code == 403


def test_rotate_endpoint_rejects_memory_backend(client, monkeypatch):
    monkeypatch.setattr(main_module, "credential_store", InMemoryCredentialStore())
    resp = client.post(
        "/connectors/credentials/rotate",
        json={"new_key": Fernet.generate_key().decode()},
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert resp.status_code == 400


def test_rotate_endpoint_rotates_with_db_backend(client, monkeypatch, db_store):
    db_store.save(_creds())
    monkeypatch.setattr(main_module, "credential_store", db_store)
    resp = client.post(
        "/connectors/credentials/rotate",
        json={"new_key": Fernet.generate_key().decode()},
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["rotated"] == 1
