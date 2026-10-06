from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class AppleOrderCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)


class WalletAdjust(BaseModel):
    telegram_id: int
    amount: int
    note: str | None = None


class PartnerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class PartnerWalletAdjust(BaseModel):
    amount: int
    note: str | None = None
