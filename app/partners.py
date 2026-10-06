from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Partner


def create_partner(session: Session, name: str) -> Partner:
    existing = session.scalar(select(Partner).where(Partner.name == name))
    if existing:
        return existing
    p = Partner(name=name)
    session.add(p)
    session.flush()
    return p


def partner_synthetic_telegram_id(partner_id: str) -> int:
    return -int(partner_id.replace("-", "")[:12], 16)
