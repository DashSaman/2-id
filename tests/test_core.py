from sqlalchemy import select
from app.config import get_settings
from app.crypto import derive_test_key
from app.models import AppleJob, LedgerEntry, Wallet
from app.orders import IdempotencyConflict, create_apple_order, create_or_get_user
from app.wallet import InsufficientBalance, adjust_wallet, ensure_wallet


def test_production_rejects_sqlite(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", derive_test_key("a"))
    monkeypatch.setenv("ADMIN_API_KEY", "a"*32)
    monkeypatch.setenv("PARTNER_KEY_PEPPER", "b"*32)
    try:
        get_settings()
    except RuntimeError as e:
        assert "SQLite" in str(e)
    else:
        raise AssertionError("production SQLite should be rejected")


def _funded(db, amount=500_000):
    with db() as s:
        u = create_or_get_user(s, 1, "u", "IRR")
        w = ensure_wallet(s, u, "IRR")
        adjust_wallet(s, w.id, amount, "ADMIN_ADJUSTMENT", "fund")
        s.commit()
        return u.id, w.id


def test_wallet_and_idempotent_order(db, crypto):
    uid, wid = _funded(db)
    req = {"email":"a@example.com","password":"12345678","first_name":"A","last_name":"B"}
    with db() as s:
        o1 = create_apple_order(s, owner_type="telegram", owner_id="1", user_id=uid, partner_id=None, wallet_id=wid, request=req, idempotency_key="k1", price=100_000, currency="IRR", crypto=crypto, fingerprint_key="pep")
        s.commit(); oid=o1.id
    with db() as s:
        o2 = create_apple_order(s, owner_type="telegram", owner_id="1", user_id=uid, partner_id=None, wallet_id=wid, request=req, idempotency_key="k1", price=100_000, currency="IRR", crypto=crypto, fingerprint_key="pep")
        s.commit()
        assert o2.id == oid
        assert s.get(Wallet,wid).balance == 400_000
        assert len(s.scalars(select(LedgerEntry)).all()) == 2
        job=s.scalar(select(AppleJob).where(AppleJob.order_id==oid))
        assert "12345678" not in job.encrypted_payload


def test_idempotency_conflict(db, crypto):
    uid,wid=_funded(db)
    req={"email":"a@example.com","password":"12345678","first_name":"A","last_name":"B"}
    with db() as s:
        create_apple_order(s, owner_type="telegram", owner_id="1", user_id=uid, partner_id=None, wallet_id=wid, request=req, idempotency_key="k", price=100_000, currency="IRR", crypto=crypto, fingerprint_key="pep")
        s.commit()
    req["email"]="b@example.com"
    with db() as s:
        try:
            create_apple_order(s, owner_type="telegram", owner_id="1", user_id=uid, partner_id=None, wallet_id=wid, request=req, idempotency_key="k", price=100_000, currency="IRR", crypto=crypto, fingerprint_key="pep")
        except IdempotencyConflict:
            pass
        else:
            raise AssertionError("conflict expected")


def test_insufficient_balance(db, crypto):
    with db() as s:
        u=create_or_get_user(s,2,None,"IRR"); w=ensure_wallet(s,u,"IRR"); s.commit(); uid=u.id; wid=w.id
    with db() as s:
        try:
            create_apple_order(s, owner_type="telegram", owner_id="2", user_id=uid, partner_id=None, wallet_id=wid, request={"email":"a@x.com","password":"12345678","first_name":"A","last_name":"B"}, idempotency_key="x", price=1, currency="IRR", crypto=crypto, fingerprint_key="p")
        except InsufficientBalance:
            pass
        else:
            raise AssertionError("insufficient balance expected")


def test_partner_synthetic_id_is_stable():
    from app.partners import partner_synthetic_telegram_id
    pid="12345678-1234-1234-1234-123456789abc"
    assert partner_synthetic_telegram_id(pid) == partner_synthetic_telegram_id(pid)
    assert partner_synthetic_telegram_id(pid) < 0
