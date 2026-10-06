from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_, select

from .config import get_settings
from .crypto import PayloadCrypto
from .db import make_engine, make_session_factory
from .logging import configure_logging
from .models import AppleJob, Order, Wallet
from .providers.base import AppleAccountRequest
from .providers.manual import ManualAppleProvider
from .providers.mock import MockAppleProvider
from .wallet import adjust_wallet

log = logging.getLogger("twoid.worker")
TERMINAL = {"CREATED", "FAILED", "PHONE_VERIFICATION_REQUIRED", "ACTION_REQUIRED"}


def _provider(settings):
    if settings.apple_provider == "mock":
        return MockAppleProvider(settings.mock_provider_mode)
    if settings.apple_provider == "manual":
        return ManualAppleProvider()
    raise RuntimeError(f"Unsupported APPLE_PROVIDER: {settings.apple_provider}")


def claim_job(session, lease_seconds: int = 120) -> AppleJob | None:
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)
    stmt = (
        select(AppleJob)
        .where(
            or_(
                AppleJob.status.in_(["PENDING", "RETRYABLE"]),
                (AppleJob.status == "PROCESSING") & (AppleJob.locked_at.is_not(None)) & (AppleJob.locked_at < stale_before),
            ),
            AppleJob.attempt_count < AppleJob.max_attempts,
        )
        .order_by(AppleJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = session.scalar(stmt)
    if not job:
        return None
    job.status = "PROCESSING"
    job.attempt_count += 1
    job.locked_at = datetime.now(timezone.utc)
    session.flush()
    return job


def _wallet_for_order(session, order: Order) -> Wallet | None:
    if order.user_id:
        return session.scalar(select(Wallet).where(Wallet.user_id == order.user_id))
    return None


def finalize(session, job: AppleJob, result) -> None:
    order = session.scalar(select(Order).where(Order.id == job.order_id).with_for_update())
    if result.retryable and job.attempt_count < job.max_attempts:
        job.status = "RETRYABLE"
        job.result_code = result.code
        order.status = "PROCESSING"
        return

    status = result.status if result.status in TERMINAL else "FAILED"
    job.status = status
    job.result_code = result.code
    order.status = status
    order.result_code = result.code

    if status != "CREATED" and not order.refunded:
        wallet = _wallet_for_order(session, order)
        if wallet:
            adjust_wallet(session, wallet.id, order.price, "REFUND", f"order-refund:{order.id}", reference=order.id)
        order.refunded = True
    job.encrypted_payload = None
    job.payload_expires_at = None


def process_one(session_factory, provider, crypto: PayloadCrypto) -> bool:
    with session_factory() as session:
        job = claim_job(session)
        if not job:
            session.rollback()
            return False
        job_id = job.id
        payload_token = job.encrypted_payload
        session.commit()

    if not payload_token:
        result = type("R", (), {"status": "FAILED", "code": "MISSING_PAYLOAD", "retryable": False})()
    else:
        data = crypto.decrypt(payload_token)
        req = AppleAccountRequest(**data)
        try:
            result = provider.create_account(req)
        except Exception:
            log.exception("provider call failed")
            result = type("R", (), {"status": "FAILED", "code": "PROVIDER_EXCEPTION", "retryable": True})()

    with session_factory() as session:
        job = session.scalar(select(AppleJob).where(AppleJob.id == job_id).with_for_update())
        finalize(session, job, result)
        session.commit()
    return True


def purge_expired_payloads(session_factory) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    with session_factory() as session:
        jobs = session.scalars(
            select(AppleJob).where(
                AppleJob.encrypted_payload.is_not(None),
                AppleJob.payload_expires_at.is_not(None),
                AppleJob.payload_expires_at < now,
            )
        ).all()
        for job in jobs:
            job.encrypted_payload = None
            job.payload_expires_at = None
            count += 1
        session.commit()
    return count


def main() -> None:
    configure_logging()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    provider = _provider(settings)
    crypto = PayloadCrypto(settings.encryption_key)
    log.info("worker started")
    while True:
        worked = process_one(sf, provider, crypto)
        purge_expired_payloads(sf)
        if not worked:
            time.sleep(1.5)


if __name__ == "__main__":
    main()
