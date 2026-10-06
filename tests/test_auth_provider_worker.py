from sqlalchemy import select
from app.auth import authenticate_partner, issue_partner_key, verify_admin
from app.models import AppleJob, LedgerEntry, Order, Partner, Wallet
from app.orders import create_apple_order, create_or_get_user
from app.providers.base import AppleAccountRequest
from app.providers.mock import MockAppleProvider
from app.wallet import adjust_wallet, ensure_wallet
from app.worker import process_one


def test_admin_compare():
    assert verify_admin("abc", "abc")
    assert not verify_admin("abd", "abc")
    assert not verify_admin(None, "abc")


def test_partner_key_is_hashed(db):
    with db() as s:
        p=Partner(name="p"); s.add(p); s.flush(); key=issue_partner_key(s,p,"pepper"); pid=p.id; s.commit()
    with db() as s:
        assert authenticate_partner(s,key,"pepper").id == pid
        from app.models import PartnerKey
        row=s.scalar(select(PartnerKey))
        assert key not in row.key_hash
        assert authenticate_partner(s,key+"x","pepper") is None


def test_mock_outcomes():
    req=AppleAccountRequest("x@example.com","12345678","A","B")
    assert MockAppleProvider("created").create_account(req).status == "CREATED"
    assert MockAppleProvider("phone").create_account(req).status == "PHONE_VERIFICATION_REQUIRED"
    assert MockAppleProvider("fail").create_account(req).status == "FAILED"


def _order(db, crypto):
    with db() as s:
        u=create_or_get_user(s,10,None,"IRR"); w=ensure_wallet(s,u,"IRR"); adjust_wallet(s,w.id,1000,"ADMIN_ADJUSTMENT","f"); s.commit(); uid=u.id; wid=w.id
    with db() as s:
        o=create_apple_order(s, owner_type="telegram", owner_id="10", user_id=uid, partner_id=None, wallet_id=wid, request={"email":"x@example.com","password":"12345678","first_name":"A","last_name":"B"}, idempotency_key="k", price=500, currency="IRR", crypto=crypto, fingerprint_key="p")
        s.commit(); return o.id,wid


def test_worker_success_deletes_payload(db, crypto):
    oid,wid=_order(db,crypto)
    assert process_one(db,MockAppleProvider("created"),crypto)
    with db() as s:
        o=s.get(Order,oid); j=s.scalar(select(AppleJob).where(AppleJob.order_id==oid)); w=s.get(Wallet,wid)
        assert o.status=="CREATED" and not o.refunded and w.balance==500
        assert j.encrypted_payload is None


def test_worker_failure_refunds_once(db, crypto):
    oid,wid=_order(db,crypto)
    assert process_one(db,MockAppleProvider("phone"),crypto)
    assert not process_one(db,MockAppleProvider("phone"),crypto)
    with db() as s:
        o=s.get(Order,oid); w=s.get(Wallet,wid)
        assert o.status=="PHONE_VERIFICATION_REQUIRED" and o.refunded and w.balance==1000
        refunds=s.scalars(select(LedgerEntry).where(LedgerEntry.kind=="REFUND")).all()
        assert len(refunds)==1


def test_stale_processing_job_is_reclaimed(db, crypto):
    from datetime import datetime, timedelta, timezone
    from app.worker import claim_job
    oid, _ = _order(db, crypto)
    with db() as s:
        job=s.scalar(select(AppleJob).where(AppleJob.order_id==oid))
        job.status="PROCESSING"
        job.locked_at=datetime.now(timezone.utc)-timedelta(minutes=10)
        job.attempt_count=1
        s.commit()
    with db() as s:
        job=claim_job(s, lease_seconds=60)
        assert job is not None
        assert job.order_id == oid
        assert job.status == "PROCESSING"
        assert job.attempt_count == 2


def test_fresh_processing_job_is_not_reclaimed(db, crypto):
    from datetime import datetime, timezone
    from app.worker import claim_job
    oid, _ = _order(db, crypto)
    with db() as s:
        job=s.scalar(select(AppleJob).where(AppleJob.order_id==oid))
        job.status="PROCESSING"
        job.locked_at=datetime.now(timezone.utc)
        job.attempt_count=1
        s.commit()
    with db() as s:
        assert claim_job(s, lease_seconds=60) is None


def test_manual_provider_never_fakes_success():
    from app.providers.manual import ManualAppleProvider
    req=AppleAccountRequest("x@example.com","12345678","A","B")
    result=ManualAppleProvider().create_account(req)
    assert result.status == "ACTION_REQUIRED"
    assert result.code == "MANUAL_FULFILLMENT_REQUIRED"
