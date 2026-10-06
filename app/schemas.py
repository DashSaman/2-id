from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class AppleOrderCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    birthdate: str | None = Field(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    region: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")


class WalletAdjust(BaseModel):
    telegram_id: int
    amount: int
    note: str | None = None


class PartnerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class PartnerWalletAdjust(BaseModel):
    amount: int
    note: str | None = None
