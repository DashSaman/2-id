from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LedgerEntry, User, Wallet


class InsufficientBalance(Exception):
    pass


def ensure_wallet(session: Session, user: User, currency: str = "IRR") -> Wallet:
    wallet = session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    if wallet:
        return wallet
    wallet = Wallet(user_id=user.id, balance=0, currency=currency)
    session.add(wallet)
    session.flush()
    return wallet


def adjust_wallet(session: Session, wallet_id: str, amount: int, kind: str, idempotency_key: str, reference: str | None = None) -> LedgerEntry:
    existing = session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))
    if existing:
        return existing
    wallet = session.scalar(select(Wallet).where(Wallet.id == wallet_id).with_for_update())
    if not wallet:
        raise LookupError("wallet_not_found")
    new_balance = wallet.balance + amount
    if new_balance < 0:
        raise InsufficientBalance("insufficient_balance")
    wallet.balance = new_balance
    entry = LedgerEntry(wallet_id=wallet.id, amount=amount, kind=kind, reference=reference, idempotency_key=idempotency_key)
    session.add(entry)
    session.flush()
    return entry
