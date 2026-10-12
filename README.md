# LedgerLite — Wallet Service & Payment Provider Mock

Production-ready microservices architecture implementing an internal USD ledger with credit purchasing, idempotent transfers, keyset pagination, rate limiting, and an external payment provider mock with HMAC webhooks and reconciliation.

---

## 🏗 Architecture Overview

```
                      +---------------------------------------+
                      |             Client / App              |
                      +---------------------------------------+
                        |                 |                 |
       1. Deposit / Transfer / Purchase   |                 | 4. Simulate Payment
                        |                 |                 |
                        v                 |                 v
            +-----------------------+     |     +-----------------------+
            |    wallet-service     |     |     |     provider-mock     |
            |     (Port 8000)       |     |     |      (Port 8001)      |
            +-----------------------+     |     +-----------------------+
              |          |         ^      |       ^                 |
   DB Query / |          |         |      |       |                 |
   Row Locks  |     2. Create      | 3. HMAC-SHA256                 |
              |        Invoice     |    Signed Webhook              |
              v          |         |      |       |                 |
        +------------+   +---------+------+       +-----------------+
        | PostgreSQL |             |                        |
        |  Database  |             +--- 5. Reconciliation --+
        +------------+                  (GET /invoices/{id})
```

### Components
1. **`wallet-service` (Port 8000)**:
   - FastAPI-based financial ledger handling accounts, deposits, internal transfers, and credit purchases.
   - Concurrency-safe transfers with row-level locks (`SELECT ... FOR UPDATE`) ordered deterministically to eliminate deadlocks.
   - Keyset (cursor-based) pagination ensuring consistent transaction history under active writes.
   - HMAC-SHA256 signature verification and replay prevention for webhooks.
   - In-memory sliding-window rate limiter (30 POST requests/minute per `X-API-Key`).
   - Deposit reconciliation endpoint and CLI command for lost webhook recovery.
2. **`provider-mock` (Port 8001)**:
   - In-memory payment gateway mock managing invoices and simulations.
   - Generates and signs webhook callbacks with HMAC-SHA256.
   - Supports invoice simulation: `/invoices/{id}/pay` and `/invoices/{id}/expire`.
3. **`ledger_postgres` (Port 5432)**:
   - PostgreSQL 16 relational database with ACID guarantees, foreign keys, and indexes.

---

## 🚀 Quick Start (Docker Compose)

### 1. Launch All Services
```bash
docker compose up --build
```
This starts:
- PostgreSQL on `localhost:5432`
- `provider-mock` on `http://localhost:8001`
- `wallet-service` on `http://localhost:8000` (auto-runs migrations & seeds initial accounts)

### 2. Verified Pre-Seeded Accounts
The seed script generates two active test accounts:
- **Alice**: API Key `test_key_alice_123`
- **Bob**: API Key `test_key_bob_456`

### 3. Interactive API Documentation
- Wallet Service Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Provider Mock Swagger UI: [http://localhost:8001/docs](http://localhost:8001/docs)

---

## 🧪 Testing

Both services feature fully isolated test suites with 100% test pass rates (94 tests total).

### Run Tests Locally
```bash
# Provider Mock test suite (24 tests)
.\provider_mock\.venv\Scripts\pytest provider_mock/tests

# Wallet Service test suite (70 tests)
.\wallet_service\.venv\Scripts\pytest wallet_service/tests

# Code style and lint checks
.\wallet_service\.venv\Scripts\ruff check wallet_service provider_mock
.\wallet_service\.venv\Scripts\ruff format --check wallet_service provider_mock
```

---

## 📡 API Reference

### Wallet Service (`http://localhost:8000`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/accounts` | None | Create a new user account with API key |
| `GET` | `/v1/accounts/me` | `X-API-Key` | Get balance (USD and credits) |
| `POST` | `/v1/deposits` | `X-API-Key` | Initiate deposit and receive invoice pay URL |
| `POST` | `/v1/transfers` | `X-API-Key` | Transfer USD to another account (idempotent) |
| `POST` | `/v1/purchases` | `X-API-Key` | Purchase credits with USD balance (tiered discount) |
| `GET` | `/v1/transactions` | `X-API-Key` | Keyset-paginated ledger transaction history |
| `POST` | `/v1/webhooks/provider` | HMAC Header | Ingest signed invoice webhook from provider |
| `POST` | `/v1/reconciliation/run` | None | Reconcile pending deposits older than N minutes |
| `GET` | `/health` | None | Health check endpoint |

### Provider Mock (`http://localhost:8001`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/invoices` | Bearer Token | Create payment invoice |
| `GET` | `/invoices/{id}` | Bearer Token | Fetch invoice status and details |
| `POST` | `/invoices/{id}/pay` | Bearer Token | Simulate successful customer payment |
| `POST` | `/invoices/{id}/expire` | Bearer Token | Simulate expired unpaid invoice |
| `GET` | `/health` | None | Health check endpoint |

---

## 🛠 CLI Utilities

### Seed Initial Accounts
```bash
python -m wallet_service.scripts.seed
```

### Run Deposit Reconciliation
```bash
# Reconcile pending deposits older than 5 minutes
python -m wallet_service.scripts.reconcile --minutes 5
```

---

## 🏛 Key Design Decisions & Trade-Offs

### 1. Keyset (Cursor-Based) vs. Offset Pagination
- **Decision**: Implemented cursor-based pagination using `(created_at, id)` composite keys instead of `OFFSET / LIMIT`.
- **Trade-off**: Keyset pagination does not allow arbitrary "jump to page N" navigation, but guarantees $O(1)$ database execution performance regardless of table depth and prevents duplicate/skipped records when new transactions are inserted concurrently.

### 2. Deadlock-Free Concurrency via Deterministic Row Locking
- **Decision**: In `/v1/transfers`, row locks (`SELECT ... FOR UPDATE`) are acquired strictly in alphabetical order of account IDs (`min(sender_id, receiver_id)` followed by `max(...)`).
- **Trade-off**: Adds a small sorting overhead, but mathematically guarantees zero deadlocks between concurrent cross-transfers (e.g. Alice sending to Bob while Bob sends to Alice).

### 3. Strict String-to-Decimal Financial Arithmetic
- **Decision**: All financial amounts in JSON payloads must be formatted as strings with exactly two decimal places (`"10.00"`). Floats or more than two decimal places return HTTP 422. Provider fee (1.5%) and volume discounts use `ROUND_HALF_UP`.
- **Trade-off**: Rejects casual unquoted JSON numbers (`{"amount": 10}`), but prevents IEEE 754 binary floating-point inaccuracy and silent rounding bugs.

### 4. Two-Phase Webhook Ingestion & Idempotency
- **Decision**: Incoming webhooks verify HMAC-SHA256 before touching the database. Processed webhooks are recorded in `processed_webhooks` table. If the deposit is already in a final state (`paid` or `expired`), subsequent webhooks return HTTP 200 without duplicate credit execution.
- **Trade-off**: Requires dedicated ledger locking and event tracking, but ensures bulletproof idempotency under retries and network race conditions.

### 5. ASGI Sliding-Window Rate Limiting
- **Decision**: Implemented a pure ASGI sliding-window rate limiter tracking timestamps per `X-API-Key` (30 POST requests/min).
- **Trade-off**: In-memory state is local to the instance (Redis recommended for horizontal multi-replica scaling), but avoids external decorator bugs (e.g., SlowAPI response type collisions) and returns standard RFC `429 Too Many Requests` with `Retry-After`.

### 6. Automated Reconciliation
- **Decision**: Added an automated reconciliation process scanning deposits stuck in `pending` longer than a specified threshold.
- **Trade-off**: Generates outbound HTTP queries to the provider, but automatically self-heals accounts when external webhooks fail, are dropped by network firewalls, or timeout.
