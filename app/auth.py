from __future__ import annotations

import hashlib
import hmac
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Partner, PartnerKey


def verify_admin(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def _hash_partner_key(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def issue_partner_key(session: Session, partner: Partner, pepper: str) -> str:
    prefix = secrets.token_hex(5)
    secret = secrets.token_urlsafe(32)
    session.add(PartnerKey(partner_id=partner.id, prefix=prefix, key_hash=_hash_partner_key(secret, pepper)))
    session.flush()
    return f"twoid_{prefix}.{secret}"


def authenticate_partner(session: Session, token: str | None, pepper: str) -> Partner | None:
    if not token or not token.startswith("twoid_") or "." not in token:
        return None
    head, secret = token.split(".", 1)
    prefix = head.removeprefix("twoid_")
    key = session.scalar(select(PartnerKey).where(PartnerKey.prefix == prefix, PartnerKey.active.is_(True)))
    if not key or not hmac.compare_digest(key.key_hash, _hash_partner_key(secret, pepper)):
        return None
    return session.scalar(select(Partner).where(Partner.id == key.partner_id, Partner.active.is_(True)))
