from __future__ import annotations

from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import PayloadCrypto, fingerprint
from .models import AppleJob, Order, User, now_utc
from .wallet import adjust_wallet, ensure_wallet


class IdempotencyConflict(Exception):
    pass


def mask_email(email: str) -> str:
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    if len(local) <= 2:
        masked = local[0:1] + "***"
    else:
        masked = local[:2] + "***"
    return f"{masked}@{domain}"


def create_or_get_user(session: Session, telegram_id: int, username: str | None, currency: str) -> User:
    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        session.flush()
        ensure_wallet(session, user, currency)
    elif username and user.username != username:
        user.username = username
    return user


def create_apple_order(
    session: Session,
    *,
    owner_type: str,
    owner_id: str,
    user_id: str | None,
    partner_id: str | None,
    wallet_id: str,
    request: dict,
    idempotency_key: str,
    price: int,
    currency: str,
    crypto: PayloadCrypto,
    fingerprint_key: str,
) -> Order:
    fp = fingerprint(request, fingerprint_key)
    existing = session.scalar(
        select(Order).where(
            Order.owner_type == owner_type,
            Order.owner_id == owner_id,
            Order.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.request_fingerprint != fp:
            raise IdempotencyConflict("idempotency_key_reused_with_different_request")
        return existing

    adjust_wallet(session, wallet_id, -price, "PURCHASE", f"order-debit:{owner_type}:{owner_id}:{idempotency_key}")
    order = Order(
        user_id=user_id,
        partner_id=partner_id,
        owner_type=owner_type,
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        email_masked=mask_email(request["email"]),
        price=price,
        currency=currency,
        status="PENDING",
    )
    session.add(order)
    session.flush()
    session.add(AppleJob(
        order_id=order.id,
        encrypted_payload=crypto.encrypt(request),
        payload_expires_at=now_utc() + timedelta(hours=1),
    ))
    session.flush()
    return order
