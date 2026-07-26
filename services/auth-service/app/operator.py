"""Single-operator bootstrap.

The platform is controlled by one operator. On startup, when OPERATOR_USERNAME
and OPERATOR_PASSWORD_HASH are set, this ensures that operator exists with the
admin role and the given bcrypt hash. The plaintext password is never stored
or read here — only its bcrypt hash, supplied via the environment.

Security notes:
- No default credentials ship with the repo any more: both the username and the
  hash come from the environment, and scripts/start-bottrading.ps1 generates a
  random pair per machine into .local/ (gitignored). The legacy hash that used
  to live in .env.example is treated as compromised — DEFAULT_OPERATOR_PASSWORD
  below still detects it so a copy-pasted old config gets flagged loudly.
- The stored hash is re-synced from the environment on every startup, so
  rotating OPERATOR_PASSWORD_HASH is enough to retire an old password.
- The operator logs in with the username, not an email; a synthetic
  `<username>@operator.local` email fills the required (unique) email column.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.models import Role, User, UserRole

logger = logging.getLogger("auth-service.operator")

DEFAULT_OPERATOR_PASSWORD = "Viruheta"


def _get_or_create_role(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


def bootstrap_operator(db: Session) -> None:
    username = os.environ.get("OPERATOR_USERNAME")
    password_hash = os.environ.get("OPERATOR_PASSWORD_HASH")
    if not username or not password_hash:
        logger.warning(
            "OPERATOR_USERNAME/OPERATOR_PASSWORD_HASH not set; single-operator "
            "account not bootstrapped (development mode)"
        )
        return

    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            email=f"{username.lower()}@operator.local",
            username=username,
            password_hash=password_hash,
        )
        db.add(user)
        db.flush()
        logger.info("operator '%s' created", username)
    else:
        # Keep the stored hash in sync with the configured one (password
        # rotation via env re-applies on restart).
        user.password_hash = password_hash

    admin_role = _get_or_create_role(db, "admin")
    has_admin = db.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id, UserRole.role_id == admin_role.id
        )
    )
    if has_admin is None:
        db.add(UserRole(user_id=user.id, role_id=admin_role.id))
    db.commit()

    if security.verify_password(DEFAULT_OPERATOR_PASSWORD, password_hash):
        logger.warning(
            "SECURITY: operator '%s' is using the old repo-published password — "
            "it is public and must be changed NOW from the panel (Seguridad) or "
            "via POST /auth/change_password",
            username,
        )
