# 2-id Product Architecture Design

Date: 2026-10-07

## Purpose

Build `2-id` as the reference Telegram service for ordering Apple-account creation, with a central API, wallet/ledger, partner integration keys, and a replaceable Apple worker. The platform must remain useful even when the underlying Apple-account creation method changes.

The initial production milestone provides a fully testable end-to-end platform with a mock Apple provider and a narrow provider interface for the real implementation. The system must never claim that phone verification can be bypassed. If Apple requires phone verification, the job returns `PHONE_VERIFICATION_REQUIRED` and the non-success billing path is applied.

## Host Boundary

This design inherits every rule in `/AGENTS.md` and `docs/superpowers/specs/2026-10-07-server-isolation-design.md`.

Project-owned production resources are limited to:

- `/opt/2-id`
- containers prefixed `twoid_`
- Docker network `twoid_internal`
- Docker subnet `172.28.235.0/24`
- Docker volumes prefixed `twoid_`
- loopback ports in `127.0.0.1:18220-18229` after a fresh preflight

The initial API binds only `127.0.0.1:18220`. Telegram uses long polling. No Apache, firewall, routing, tunnel, Xray, X-UI, Hedioum, host MySQL/PostgreSQL, or foreign Docker resource may be changed.

## Architecture

The system is split into four independently replaceable units:

1. `twoid_api`: FastAPI service for orders, wallet queries, partner access, administration, and health.
2. `twoid_bot`: aiogram Telegram bot using the same application services/API contract.
3. `twoid_worker`: database-backed job consumer that invokes an `AppleProvider` implementation.
4. `twoid_postgres`: project-owned PostgreSQL database and persistent `twoid_postgres_data` volume.

All services communicate only on `twoid_internal`. Redis is intentionally omitted. PostgreSQL is the source of truth and provides transactional job claiming using row locks with skip-locked semantics.

Logical flow:

`Telegram or Partner API -> Core API -> Order + Wallet -> Apple Job -> AppleProvider -> Result`

## Technology

- Python 3.12
- FastAPI and Uvicorn
- Pydantic v2
- SQLAlchemy 2.x with asyncpg
- Alembic
- PostgreSQL 16
- aiogram 3.x
- cryptography for application-level sensitive-payload encryption
- httpx for provider/payment adapters
- pytest + pytest-asyncio
- Docker Compose v2

Dependencies are pinned to explicit compatible ranges and production images run as non-root users where practical.

## Domain Model

### Identity

`User` represents a Telegram customer. Telegram IDs are unique. Telegram profile data is non-authoritative metadata.

`Partner` represents a third-party bot/service. Partner API keys are shown once at issuance and only a cryptographic hash is stored.

### Wallet

A wallet stores integer minor currency units. Default currency is `IRR` and is configuration-driven.

The ledger is immutable. Every balance mutation creates a ledger row with an idempotency key and a reference to its cause. Order creation debits the configured Apple-account price atomically. A terminal non-success worker result automatically refunds the corresponding debit exactly once. A successful `CREATED` order remains charged.

Administrative credits/debits require the runtime admin credential and are audited.

### Orders and Jobs

`Order` owns customer-visible status and billing state.

`AppleJob` owns worker state, retry metadata, encrypted request payload, provider result metadata, and timestamps.

Initial terminal/provider states:

- `CREATED`
- `FAILED`
- `PHONE_VERIFICATION_REQUIRED`
- `ACTION_REQUIRED`

Non-terminal states include `PENDING`, `PROCESSING`, and `RETRYABLE`.

The worker may retry only failures explicitly classified retryable. Jobs are claimed transactionally so two workers cannot process the same attempt.

## Apple Provider Boundary

The provider consumes an `AppleAccountRequest` and returns an `AppleAccountResult`. The core platform does not depend on Apple private protocols or browser implementation details.

The initial request accepts:

- email
- password
- first name
- last name

Optional provider-specific fields may be added later without changing wallet, Telegram, order, or partner APIs. If a real provider needs more user input, it returns `ACTION_REQUIRED` with a safe, non-secret reason code.

The repository includes `MockAppleProvider` for deterministic end-to-end testing. A real provider is a separate implementation of the same interface.

The platform does not implement phone-verification bypass logic. `PHONE_VERIFICATION_REQUIRED` is a first-class terminal outcome.

## Sensitive Data Policy

Apple passwords and other account credentials must never appear in application logs, API responses after submission, audit records, test fixtures committed to Git, or exceptions returned to callers.

Sensitive job payloads are encrypted at application level with a runtime-only encryption key. They are deleted immediately after a terminal job result. A cleanup task removes payloads for stuck/abandoned jobs no later than one hour after their retention deadline.

Telegram bot tokens, admin keys, partner plaintext keys, database passwords, payment credentials, and encryption keys exist only in runtime environment/secrets. Production `.env` is never committed.

Log format uses structured fields and redacts known sensitive field names.

## API Contract

All business endpoints live under `/v1`.

Initial endpoints:

- `GET /health/live`
- `GET /health/ready`
- `POST /v1/orders/apple`
- `GET /v1/orders/{order_id}`
- `GET /v1/wallet`
- `GET /v1/orders`
- `POST /v1/admin/wallet/adjust`
- `POST /v1/admin/partners`
- `POST /v1/admin/partners/{partner_id}/keys`
- `POST /v1/partner/orders/apple`
- `GET /v1/partner/orders/{order_id}`

Order creation accepts an `Idempotency-Key`. Reusing a key with the same request returns the original order; reusing it with conflicting input returns a conflict.

Partner authentication uses a bearer-style project API key. Admin endpoints use a high-entropy runtime admin key and constant-time comparison. Telegram bot identity is mapped to its user record internally.

Rate limiting protects write endpoints without adding Redis; it is process-local for the first single-API-instance deployment. The interface leaves room for a distributed limiter later.

## Telegram Experience

The main keyboard contains:

- Create Apple ID
- Wallet
- My Orders
- Support

The order wizard collects email, password, first name, and last name, summarizes non-secret fields, shows the price, and asks for confirmation before creating the order.

Passwords are never echoed in confirmations or history. Order history shows status, timestamps, email masked for display, and safe result messages.

Wallet shows balance and recent ledger entries. Initial production supports administrator credit/debit so the complete wallet flow works without choosing an external payment gateway.

## Payment Boundary

External payment processing is represented by a `PaymentProvider` interface but no shared ingress is changed in the initial deployment. Adding a real webhook-based gateway requires a separate approved ingress change because the host Apache/TLS boundary is protected.

Until a gateway is selected and its credentials are provided, wallet funding is performed through audited administrative adjustments. This is a functional funding mechanism, not a fake successful external payment.

## Error Handling

API errors use stable machine-readable codes and safe user-facing messages. Database errors roll back the transaction. Duplicate requests rely on idempotency instead of best-effort deduplication.

Worker crashes leave a lease/attempt record that becomes retryable after timeout. Retry count is bounded. Non-retryable provider outcomes are terminal and trigger sensitive-payload deletion plus billing finalization/refund.

No exception path may log decrypted payloads.

## Observability

Each order/job receives a correlation ID. Structured logs include service, correlation ID, order ID, job ID, safe status, and duration where relevant.

Health checks verify process liveness and, for readiness, PostgreSQL connectivity. Docker health checks use these endpoints.

Project logs remain inside the project/Docker logging boundary and follow the host five-day retention policy.

## Testing

Required automated coverage:

- wallet atomic debit, credit, and exactly-once refund
- insufficient balance
- idempotent order creation and conflicting idempotency reuse
- partner API authentication and key hashing
- admin authentication
- order/job state transitions
- mutually exclusive job claiming
- sensitive-payload encryption and terminal deletion
- log redaction
- mock-provider success, failure, phone-verification-required, and action-required results
- worker retry bounds
- Telegram wizard does not echo passwords
- API health/readiness
- database migrations from an empty database

A Docker smoke test must prove the full mock flow from order submission to worker completion.

## Deployment and Rollback

Every deploy repeats the mandatory preflight in `AGENTS.md`: disk floor, candidate port availability, subnet conflicts, foreign container health, critical services, routes/tunnels, and rollback scope.

Production Compose creates only `twoid_*` containers/volumes and `twoid_internal`. API publishes only `127.0.0.1:18220`.

Rollback stops/removes only `2-id` containers and network. Database volume deletion is never part of routine rollback and requires an explicit data-destruction decision.

After deployment, the same foreign-container, port, service, tunnel, disk, memory, and `2-id` health checks run again.

## Initial Completion Definition

The initial platform is complete when:

1. migrations create a clean database;
2. API, bot, worker, and database start in isolated Docker resources;
3. wallet/admin funding works;
4. Telegram and partner API can create idempotent orders;
5. the mock provider completes the end-to-end path with correct billing and secret deletion;
6. all automated tests and Docker smoke tests pass;
7. deployment on the shared VPS passes before/after production health checks;
8. no foreign server resource changes;
9. production secrets remain outside Git;
10. the real Apple provider can be added without changing Telegram, wallet, order, or partner contracts.

A real Apple provider and a real external payment gateway are integration implementations behind approved interfaces; they cannot be truthfully marked production-operational until their implementation and required external credentials are available.
