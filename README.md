# 2-id

Reference Telegram/API platform for Apple-account creation orders.

## Operational components

- isolated FastAPI core
- wallet + immutable ledger
- idempotent orders
- encrypted transient account credentials
- partner API keys with hashed-at-rest secrets
- partner wallet endpoint and admin funding
- database-backed worker queue with expired-lease recovery
- production-safe manual provider plus deterministic mock provider for tests
- Telegram reference bot when `TELEGRAM_BOT_TOKEN` is configured
- project-only Docker deployment and rollback scripts

## Provider status

Production defaults to `ManualAppleProvider`, which returns `ACTION_REQUIRED` instead of pretending an account was created. `MockAppleProvider` is available for end-to-end verification. A real provider remains behind the `AppleProvider` interface and must be implemented and validated separately. If the upstream service requires phone verification, the platform records `PHONE_VERIFICATION_REQUIRED`; it does not bypass verification.

## Production setup

1. Copy `.env.example` to `.env` outside Git.
2. Generate a Fernet key for `APP_ENCRYPTION_KEY`.
3. Generate high-entropy values for `ADMIN_API_KEY`, `PARTNER_KEY_PEPPER`, and `POSTGRES_PASSWORD`.
4. Keep `TELEGRAM_BOT_TOKEN` empty until a bot token is provided.
5. Run `scripts/preflight.sh`.
6. Run `scripts/deploy.sh`.
7. Run `scripts/smoke.sh`.

API listens only on `127.0.0.1:18220`.

## Partner flow

1. Create the partner with the admin endpoint.
2. Issue the partner API key. Plaintext is returned once; only its hash is stored.
3. Fund the partner with `POST /v1/admin/partners/{partner_id}/wallet/adjust`.
4. Partner checks `GET /v1/partner/wallet`.
5. Partner submits `POST /v1/partner/orders/apple` with Bearer key and `Idempotency-Key`.

## Payments

The initial wallet funding path is audited admin adjustment. A real gateway is intentionally not faked: it belongs behind the payment adapter and requires actual gateway credentials and an approved ingress/webhook design.

## Safety boundary

See `AGENTS.md` and the server-isolation spec. Runtime ownership is restricted to `/opt/2-id`, `twoid_*`, `twoid_internal`, `172.28.235.0/24`, and approved loopback ports.
