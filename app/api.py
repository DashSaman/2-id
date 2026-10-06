from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import select, text

from .auth import authenticate_partner, issue_partner_key, verify_admin
from .config import get_settings
from .crypto import PayloadCrypto
from .db import make_engine, make_session_factory
from .models import AuditLog, Order, Partner, User
from .orders import IdempotencyConflict, create_apple_order, create_or_get_user
from .partners import create_partner, partner_synthetic_telegram_id
from .schemas import AppleOrderCreate, PartnerCreate, PartnerWalletAdjust, WalletAdjust
from .wallet import InsufficientBalance, adjust_wallet, ensure_wallet
from .external_worker import router as external_worker_router

settings = get_settings()
engine = make_engine(settings.database_url)
SessionFactory = make_session_factory(engine)
crypto = PayloadCrypto(settings.encryption_key) if settings.encryption_key else None
app = FastAPI(title="2-id", version="0.1.0")
app.include_router(external_worker_router)

_rate = defaultdict(deque)
_rate_lock = threading.Lock()


def rate_limit(key: str, limit: int = 30, window: int = 60):
    now = time.time()
    with _rate_lock:
        q = _rate[key]
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, detail={"code": "RATE_LIMITED"})
        q.append(now)


def _admin(x_admin_key: str | None = Header(default=None)):
    if not verify_admin(x_admin_key, settings.admin_api_key):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED"})


def _partner(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ") if authorization else None
    with SessionFactory() as session:
        partner = authenticate_partner(session, token, settings.partner_key_pepper)
        if not partner:
            raise HTTPException(401, detail={"code": "INVALID_PARTNER_KEY"})
        return {"id": partner.id, "name": partner.name}


def order_view(order: Order) -> dict:
    return {
        "id": order.id,
        "email": order.email_masked,
        "status": order.status,
        "result_code": order.result_code,
        "price": order.price,
        "currency": order.currency,
        "refunded": order.refunded,
        "created_at": order.created_at,
    }


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        with SessionFactory() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})


@app.post("/v1/admin/wallet/adjust", dependencies=[Depends(_admin)])
def admin_wallet_adjust(body: WalletAdjust):
    rate_limit("admin-wallet", 60)
    with SessionFactory() as session:
        user = create_or_get_user(session, body.telegram_id, None, settings.currency)
        wallet = ensure_wallet(session, user, settings.currency)
        entry = adjust_wallet(session, wallet.id, body.amount, "ADMIN_ADJUSTMENT", f"admin:{body.telegram_id}:{time.time_ns()}", body.note)
        session.add(AuditLog(actor="admin", action="wallet.adjust", target=user.id, detail=str(body.amount)))
        session.commit()
        return {"telegram_id": body.telegram_id, "balance": wallet.balance, "currency": wallet.currency, "entry_id": entry.id}


@app.post("/v1/admin/partners", dependencies=[Depends(_admin)])
def admin_partner_create(body: PartnerCreate):
    with SessionFactory() as session:
        partner = create_partner(session, body.name)
        session.add(AuditLog(actor="admin", action="partner.create", target=partner.id))
        session.commit()
        return {"id": partner.id, "name": partner.name}


@app.post("/v1/admin/partners/{partner_id}/keys", dependencies=[Depends(_admin)])
def admin_partner_key(partner_id: str):
    with SessionFactory() as session:
        partner = session.get(Partner, partner_id)
        if not partner:
            raise HTTPException(404, detail={"code": "PARTNER_NOT_FOUND"})
        key = issue_partner_key(session, partner, settings.partner_key_pepper)
        session.add(AuditLog(actor="admin", action="partner.key.issue", target=partner.id))
        session.commit()
        return {"api_key": key}


@app.post("/v1/admin/partners/{partner_id}/wallet/adjust", dependencies=[Depends(_admin)])
def admin_partner_wallet_adjust(partner_id: str, body: PartnerWalletAdjust):
    with SessionFactory() as session:
        partner = session.get(Partner, partner_id)
        if not partner:
            raise HTTPException(404, detail={"code": "PARTNER_NOT_FOUND"})
        synthetic = partner_synthetic_telegram_id(partner.id)
        user = create_or_get_user(session, synthetic, f"partner:{partner.name}", settings.currency)
        wallet = ensure_wallet(session, user, settings.currency)
        entry = adjust_wallet(session, wallet.id, body.amount, "ADMIN_ADJUSTMENT", f"partner-admin:{partner.id}:{time.time_ns()}", body.note)
        session.add(AuditLog(actor="admin", action="partner.wallet.adjust", target=partner.id, detail=str(body.amount)))
        session.commit()
        return {"partner_id": partner.id, "balance": wallet.balance, "currency": wallet.currency, "entry_id": entry.id}


@app.get("/v1/partner/wallet")
def partner_wallet(partner=Depends(_partner)):
    synthetic = partner_synthetic_telegram_id(partner["id"])
    with SessionFactory() as session:
        user = session.scalar(select(User).where(User.telegram_id == synthetic))
        if not user:
            return {"balance": 0, "currency": settings.currency}
        wallet = ensure_wallet(session, user, settings.currency)
        return {"balance": wallet.balance, "currency": wallet.currency}


@app.post("/v1/partner/orders/apple")
def partner_order(body: AppleOrderCreate, partner=Depends(_partner), idempotency_key: str = Header(alias="Idempotency-Key")):
    rate_limit(f"partner:{partner['id']}", 30)
    if not crypto:
        raise HTTPException(503, detail={"code": "ENCRYPTION_NOT_CONFIGURED"})
    synthetic = partner_synthetic_telegram_id(partner["id"])
    with SessionFactory() as session:
        user = create_or_get_user(session, synthetic, f"partner:{partner['name']}", settings.currency)
        wallet = ensure_wallet(session, user, settings.currency)
        try:
            order = create_apple_order(
                session,
                owner_type="partner",
                owner_id=partner["id"],
                user_id=user.id,
                partner_id=partner["id"],
                wallet_id=wallet.id,
                request=body.model_dump(mode="json"),
                idempotency_key=idempotency_key,
                price=settings.apple_account_price,
                currency=settings.currency,
                crypto=crypto,
                fingerprint_key=settings.partner_key_pepper,
            )
            session.commit()
        except InsufficientBalance:
            session.rollback()
            raise HTTPException(402, detail={"code": "INSUFFICIENT_BALANCE"})
        except IdempotencyConflict:
            session.rollback()
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
        return order_view(order)


@app.get("/v1/partner/orders/{order_id}")
def partner_get_order(order_id: str, partner=Depends(_partner)):
    with SessionFactory() as session:
        order = session.scalar(select(Order).where(Order.id == order_id, Order.partner_id == partner["id"]))
        if not order:
            raise HTTPException(404, detail={"code": "ORDER_NOT_FOUND"})
        return order_view(order)
