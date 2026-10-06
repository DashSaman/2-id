from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    encryption_key: str
    admin_api_key: str
    partner_key_pepper: str
    apple_account_price: int
    currency: str
    apple_provider: str
    mock_provider_mode: str
    telegram_bot_token: str | None
    admin_telegram_ids: tuple[int, ...]
    support_text: str
    api_bind: str
    api_port: int

    @property
    def production(self) -> bool:
        return self.app_env.lower() == "production"

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and telegram_id in self.admin_telegram_ids


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return tuple(values)


def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "development")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./twoid.db")
    encryption_key = os.getenv("APP_ENCRYPTION_KEY", "")
    admin_key = os.getenv("ADMIN_API_KEY", "")
    pepper = os.getenv("PARTNER_KEY_PEPPER", "")
    if env.lower() == "production":
        missing = [
            name
            for name, value in {
                "DATABASE_URL": os.getenv("DATABASE_URL"),
                "APP_ENCRYPTION_KEY": encryption_key,
                "ADMIN_API_KEY": admin_key,
                "PARTNER_KEY_PEPPER": pepper,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing production configuration: {', '.join(missing)}")
        if database_url.startswith("sqlite"):
            raise RuntimeError("Production DATABASE_URL must not use SQLite")
    return Settings(
        app_env=env,
        database_url=database_url,
        encryption_key=encryption_key,
        admin_api_key=admin_key,
        partner_key_pepper=pepper,
        apple_account_price=int(os.getenv("APPLE_ACCOUNT_PRICE", "100000")),
        currency=os.getenv("CURRENCY", "IRR"),
        apple_provider=os.getenv("APPLE_PROVIDER", "mock"),
        mock_provider_mode=os.getenv("MOCK_PROVIDER_MODE", "created"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        admin_telegram_ids=_parse_admin_ids(os.getenv("ADMIN_TELEGRAM_IDS", "")),
        support_text=os.getenv("SUPPORT_TEXT", "برای پشتیبانی با ادمین تماس بگیرید."),
        api_bind=os.getenv("API_BIND", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
    )
