# 2-id Core Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy the isolated 2-id Telegram/API/wallet/order platform with a database-backed worker queue and replaceable Apple provider.

**Architecture:** FastAPI, aiogram, worker, and PostgreSQL run as project-owned Docker services on `twoid_internal`. PostgreSQL provides persistence, immutable wallet ledger, idempotency, and transactional job claiming. Apple and payment implementations sit behind narrow adapters.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, asyncpg, Alembic, aiogram 3, cryptography, PostgreSQL 16, pytest, Docker Compose v2.

**Spec:** `docs/superpowers/specs/2026-10-07-product-architecture-design.md`

## Global Constraints

- Obey `AGENTS.md` and the server-isolation spec on every server mutation.
- Production ownership is limited to `/opt/2-id`, `twoid_*`, `twoid_internal`, `172.28.235.0/24`, and freshly verified `127.0.0.1:18220-18229`.
- Never commit runtime secrets or production `.env`.
- API binds to `127.0.0.1:18220` only.
- No Apache/firewall/route/tunnel/shared-database changes.
- Real Apple/payment integrations are not reported operational without their actual implementation and credentials.
- Apple phone verification is never bypassed; it is a first-class provider outcome.

## Review Focus

- Concurrent duplicate submissions must create/debit only one order.
- Concurrent workers must never claim the same job attempt.
- Every terminal non-success order must refund exactly once.
- No plaintext Apple password may survive terminal processing or appear in logs/API history.
- Partner/admin authentication must fail closed and never store partner plaintext keys.

---

### Task 1: Application Skeleton, Configuration, and Safe Logging

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`
- Create: `app/__init__.py`, `app/config.py`, `app/logging.py`
- Test: `tests/test_config.py`, `tests/test_logging.py`

**Interfaces:**
- Produces: `Settings`, `get_settings()`, and structured redaction utilities used by all services.

- [ ] Write failing tests for required secrets in production mode, safe defaults in test mode, and recursive password/token/key redaction.
- [ ] Run `pytest tests/test_config.py tests/test_logging.py -q` and verify failure.
- [ ] Implement the minimal settings and logging/redaction code.
- [ ] Re-run the tests and verify pass.
- [ ] Commit as `feat: add secure application foundation`.

### Task 2: Database Model, Migration, and Wallet Ledger

**Files:**
- Create: `app/db.py`, `app/models.py`, `app/wallet.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`
- Test: `tests/test_wallet.py`, `tests/test_migrations.py`

**Interfaces:**
- Produces: async session factory; User, Wallet, LedgerEntry, Order, AppleJob, Partner, PartnerKey, AuditLog models; atomic `adjust_wallet()` and `debit_for_order()`.

- [ ] Write failing tests for credit/debit, insufficient balance, immutable ledger references, duplicate idempotency, and migration from empty PostgreSQL.
- [ ] Run the focused tests and verify failure.
- [ ] Implement schema and transactional wallet functions using integer minor units and row locks.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: add wallet ledger and database schema`.

### Task 3: Orders, Idempotency, and Encrypted Job Payloads

**Files:**
- Create: `app/crypto.py`, `app/orders.py`, `app/schemas.py`
- Test: `tests/test_orders.py`, `tests/test_crypto.py`

**Interfaces:**
- Produces: `create_apple_order()`, `get_order()`, encrypted payload helpers, stable order/job state enums.

- [ ] Write failing tests proving same-key/same-request reuse, same-key/conflicting-request conflict, atomic debit+job creation, password encryption, and no password in serialized order history.
- [ ] Run focused tests and verify failure.
- [ ] Implement the order transaction and encryption boundary.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: add idempotent encrypted apple orders`.

### Task 4: Admin and Partner Authentication

**Files:**
- Create: `app/auth.py`, `app/partners.py`
- Test: `tests/test_auth.py`, `tests/test_partners.py`

**Interfaces:**
- Produces: constant-time admin auth, partner key issuance, partner key hashing/verification, partner ownership checks.

- [ ] Write failing tests for wrong/missing admin key, one-time partner plaintext key issuance, hashed storage, revoked/invalid key rejection, and cross-partner order isolation.
- [ ] Run focused tests and verify failure.
- [ ] Implement authentication and partner services.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: add admin and partner authentication`.

### Task 5: Apple Provider Interface and Worker

**Files:**
- Create: `app/providers/base.py`, `app/providers/mock.py`, `app/worker.py`
- Test: `tests/test_provider.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `AppleProvider.create_account()`, `MockAppleProvider`, transactional `claim_job()`, `process_job()`, retry/refund/cleanup behavior.

- [ ] Write failing tests for mock outcomes, skip-locked mutual exclusion, retry limit, success capture, exactly-once non-success refund, and terminal/stale sensitive-payload deletion.
- [ ] Run focused tests and verify failure.
- [ ] Implement provider protocol, deterministic mock provider, and worker loop.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: add replaceable apple worker`.

### Task 6: FastAPI and Payment Boundary

**Files:**
- Create: `app/api.py`, `app/dependencies.py`
- Create: `app/payments/base.py`, `app/payments/manual.py`
- Test: `tests/test_api.py`, `tests/test_payment_boundary.py`

**Interfaces:**
- Produces: health/readiness, user/admin/partner v1 endpoints, API error codes, `PaymentProvider` protocol.

- [ ] Write failing API tests for health, insufficient balance, admin wallet adjustment, idempotent orders, partner auth, safe order serialization, and process-local rate limits.
- [ ] Run focused tests and verify failure.
- [ ] Implement endpoints and manual funding boundary.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: expose core and partner api`.

### Task 7: Telegram Bot

**Files:**
- Create: `app/bot.py`, `app/bot_handlers.py`, `app/bot_keyboards.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: order/wallet services from Tasks 2-3.
- Produces: long-polling bot with Create Apple ID, Wallet, My Orders, and Support flows.

- [ ] Write failing handler tests for the four main actions, order wizard, price confirmation, insufficient balance, masked history, and password non-echo.
- [ ] Run focused tests and verify failure.
- [ ] Implement FSM handlers and keyboards.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat: add telegram reference bot`.

### Task 8: Containers, Operations, and End-to-End Smoke Test

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Create: `scripts/preflight.sh`, `scripts/smoke.sh`, `scripts/rollback.sh`
- Create: `README.md`
- Test: `tests/test_compose_contract.py`

**Interfaces:**
- Produces: isolated `twoid_api`, `twoid_bot`, `twoid_worker`, `twoid_postgres`, `twoid_internal`, and project-only rollback.

- [ ] Write failing static contract tests proving exact container/network/volume/subnet/loopback-port names and absence of forbidden mounts/networks.
- [ ] Run tests and verify failure.
- [ ] Implement Docker/Compose, project-scoped ops scripts, health checks, and operator docs.
- [ ] Run full `pytest -q` and Compose config validation.
- [ ] Run local/container mock-flow smoke test and verify order completion, billing, and payload deletion.
- [ ] Commit as `feat: add isolated production deployment`.

### Task 9: Production Preflight, Deploy, and Verification

**Files:**
- Modify only server path: `/opt/2-id` and project-owned Docker resources.
- No repository code change unless verification exposes a project bug.

**Interfaces:**
- Consumes: Task 8 deployment contract.
- Produces: verified production deployment or a stop report at the first failed gate.

- [ ] Capture foreign container/service/port/tunnel/disk/memory baseline.
- [ ] Verify at least 5 GiB free, `127.0.0.1:18220` free, and `172.28.235.0/24` non-overlapping.
- [ ] Verify required runtime secrets exist without printing their values; if bot token is absent, deploy API/worker/db and keep bot profile disabled rather than invent credentials.
- [ ] Deploy only explicit `twoid_*` resources.
- [ ] Run migration, readiness check, and production mock smoke flow.
- [ ] Repeat the complete foreign-resource health check and compare with baseline.
- [ ] Exercise project-only rollback procedure non-destructively/dry-run and document the exact recovery command.
- [ ] Commit any necessary project bugfixes only after reproducing and testing them.
