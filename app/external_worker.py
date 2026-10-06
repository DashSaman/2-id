from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from .config import get_settings
from .crypto import PayloadCrypto
from .db import make_engine, make_session_factory
from .models import AppleChallenge, AppleJob, Order, now_utc
from .providers.base import AppleAccountResult
from .worker import claim_job, finalize

settings = get_settings()
engine = make_engine(settings.database_url)
SessionFactory = make_session_factory(engine)
crypto = PayloadCrypto(settings.encryption_key)
router = APIRouter(prefix="/v1/worker", tags=["worker"])


class WorkerChallengeCreate(BaseModel):
    kind: str


class WorkerResult(BaseModel):
    status: str
    code: str | None = None


def _authorized(key: str | None) -> None:
    if not key or not settings.worker_api_key or not hmac.compare_digest(key, settings.worker_api_key):
        raise HTTPException(401, detail={"code": "INVALID_WORKER_KEY"})


def _external_mode() -> None:
    if settings.apple_provider != "external_windows":
        raise HTTPException(409, detail={"code": "EXTERNAL_WORKER_DISABLED"})


@router.post("/jobs/claim")
def claim(x_worker_key: str | None = Header(default=None)):
    _authorized(x_worker_key)
    _external_mode()
    with SessionFactory() as session:
        job = claim_job(session, lease_seconds=300)
        if not job:
            session.rollback()
            return Response(status_code=204)
        order = session.scalar(select(Order).where(Order.id == job.order_id))
        if not job.encrypted_payload:
            finalize(session, job, AppleAccountResult("FAILED", "MISSING_PAYLOAD"))
            session.commit()
            raise HTTPException(409, detail={"code": "MISSING_PAYLOAD"})
        payload = crypto.decrypt(job.encrypted_payload)
        result = {
            "job_id": job.id,
            "order_id": order.id,
            "attempt": job.attempt_count,
            "payload": {
                "email": payload["email"],
                "password": payload["password"],
                "first_name": payload["first_name"],
                "last_name": payload["last_name"],
            },
        }
        session.commit()
        return result


@router.post("/jobs/{job_id}/challenge")
def create_challenge(job_id: str, body: WorkerChallengeCreate, x_worker_key: str | None = Header(default=None)):
    _authorized(x_worker_key)
    _external_mode()
    if body.kind != "email_otp":
        raise HTTPException(400, detail={"code": "UNSUPPORTED_CHALLENGE"})
    with SessionFactory() as session:
        job = session.scalar(select(AppleJob).where(AppleJob.id == job_id).with_for_update())
        if not job:
            raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
        order = session.scalar(select(Order).where(Order.id == job.order_id).with_for_update())
        challenge = session.scalar(select(AppleChallenge).where(AppleChallenge.job_id == job.id))
        if not challenge:
            challenge = AppleChallenge(job_id=job.id, kind=body.kind)
            session.add(challenge)
        challenge.kind = body.kind
        challenge.encrypted_value = None
        challenge.expires_at = now_utc() + timedelta(minutes=10)
        challenge.consumed_at = None
        job.status = "WAITING_EMAIL_OTP"
        order.status = "EMAIL_OTP_REQUIRED"
        session.commit()
        return {"status": "waiting", "kind": body.kind, "order_id": order.id}


@router.get("/jobs/{job_id}/challenge")
def get_challenge(job_id: str, x_worker_key: str | None = Header(default=None)):
    _authorized(x_worker_key)
    _external_mode()
    with SessionFactory() as session:
        challenge = session.scalar(
            select(AppleChallenge).where(AppleChallenge.job_id == job_id).with_for_update()
        )
        if not challenge or not challenge.encrypted_value or challenge.consumed_at is not None:
            session.rollback()
            return Response(status_code=204)
        if challenge.expires_at and challenge.expires_at < now_utc():
            challenge.encrypted_value = None
            session.commit()
            raise HTTPException(410, detail={"code": "CHALLENGE_EXPIRED"})
        value = crypto.decrypt(challenge.encrypted_value)["value"]
        challenge.encrypted_value = None
        challenge.consumed_at = now_utc()
        job = session.scalar(select(AppleJob).where(AppleJob.id == job_id).with_for_update())
        order = session.scalar(select(Order).where(Order.id == job.order_id).with_for_update())
        job.status = "PROCESSING"
        job.locked_at = now_utc()
        order.status = "PROCESSING"
        session.commit()
        return {"kind": challenge.kind, "value": value}


@router.post("/jobs/{job_id}/result")
def result(job_id: str, body: WorkerResult, x_worker_key: str | None = Header(default=None)):
    _authorized(x_worker_key)
    _external_mode()
    allowed = {"CREATED", "FAILED", "PHONE_VERIFICATION_REQUIRED", "ACTION_REQUIRED"}
    if body.status not in allowed:
        raise HTTPException(400, detail={"code": "INVALID_RESULT_STATUS"})
    with SessionFactory() as session:
        job = session.scalar(select(AppleJob).where(AppleJob.id == job_id).with_for_update())
        if not job:
            raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
        finalize(session, job, AppleAccountResult(body.status, body.code, retryable=False))
        challenge = session.scalar(select(AppleChallenge).where(AppleChallenge.job_id == job.id))
        if challenge:
            challenge.encrypted_value = None
            challenge.consumed_at = now_utc()
        session.commit()
        return {"status": job.status, "job_id": job.id, "order_id": job.order_id}
