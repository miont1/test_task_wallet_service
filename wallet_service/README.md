# Wallet Service

Internal USD ledger and credit management system for LedgerLite.
Handles account balances, external payment gateway deposits, concurrency-safe transfers with row locking, credit purchasing with volume tiers, keyset transaction pagination, sliding-window rate limiting, and automated deposit reconciliation.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/wallet_db` | Async SQLAlchemy PostgreSQL connection string |
| `PROVIDER_BASE_URL` | `http://localhost:8001` | Base URL of payment provider mock service |
| `PROVIDER_API_KEY` | `mock-provider-key-123` | Provider API authorization key |
| `WEBHOOK_SECRET` | `mock-webhook-secret-456` | Shared secret key for verifying inbound HMAC signatures |
| `CALLBACK_URL` | `http://wallet-service:8000/v1/webhooks/provider` | Callback URL registered during invoice creation |
| `PROVIDER_TIMEOUT_SECONDS` | `5.0` | Timeout in seconds for outbound provider HTTP requests |
| `WALLET_PORT` | `8000` | Service HTTP port |

---

## 🚀 Running Locally

### 1. Create and Activate Virtual Environment
```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Database Migrations
```bash
# Ensure PostgreSQL is running, then run migrations:
alembic upgrade head
```

### 4. Seed Initial Test Accounts
```bash
python -m wallet_service.scripts.seed
```
Generates two default test accounts:
- **Alice**: `test_key_alice_123`
- **Bob**: `test_key_bob_456`

### 5. Start the Server
```bash
uvicorn wallet_service.main:app --reload --port 8000
```

Interactive Swagger UI documentation is available at: [http://localhost:8000/docs](http://localhost:8000/docs).

---

## 🐳 Docker Deployment

```bash
# Build Docker image
docker build -t wallet-service wallet_service/

# Run container (requires network access to PostgreSQL and provider-mock)
docker run -p 8000:8000 --env-file .env wallet-service
```

Or orchestrated via the repository root:
```bash
docker compose up --build
```

---

## 🧪 Testing

The service includes 70 tests covering concurrency, financial precision, idempotency, keyset pagination, rate limiting, and reconciliation.

```bash
# Run full wallet service test suite
pytest wallet_service/tests -v

# Run code style and formatting checks
ruff check wallet_service
ruff format --check wallet_service
```

---

## 📡 API Reference

Endpoints requiring user authentication expect the header:
`X-API-Key: <account_api_key>`

### 1. Accounts
- **`POST /v1/accounts`**
  - Creates a new wallet account.
  - Returns `account_id`, `api_key`, `balance_usd: "0.00"`, `balance_credits: 0`.
- **`GET /v1/accounts/me`**
  - Returns the authenticated user's current USD and credit balances.

### 2. Deposits
- **`POST /v1/deposits`**
  - Creates a pending deposit and creates an invoice with the external provider.
  - Request: `{"amount": "100.00"}`
  - Response: `{"deposit_id": "...", "status": "pending", "amount": "100.00", "pay_url": "..."}`

### 3. Transfers
- **`POST /v1/transfers`**
  - Concurrency-safe, deadlock-free USD transfer between accounts with idempotency.
  - Request:
    ```json
    {
      "to_account_id": "acc_receiver_id",
      "amount": "25.00",
      "idempotency_key": "unique-uuid-or-key"
    }
    ```
  - Acquires row locks (`SELECT ... FOR UPDATE`) in deterministic alphabetical order.

### 4. Credit Purchases
- **`POST /v1/purchases`**
  - Purchases credits using the user's USD ledger balance.
  - Base price: $0.10 per credit.
  - Tiered discounts:
    - $\ge 500$ credits: 5% discount
    - $\ge 1000$ credits: 12.5% discount (rounded half-up)
  - Request: `{"credits": 600}`
  - Response: `{"credits": 600, "total_cost_usd": "57.00", "discount_applied_percent": "5.0"}`

### 5. Transaction History
- **`GET /v1/transactions`**
  - Keyset (cursor-based) paginated ledger history.
  - Query parameters:
    - `cursor`: Base64-encoded token combining `created_at` and `id`
    - `limit`: Page size (default: 20, max: 100)
  - Response contains `items` and `next_cursor` (null if last page).

### 6. Provider Webhook Ingestion
- **`POST /v1/webhooks/provider`**
  - Ingests signed payment notifications from `provider-mock`.
  - Verifies `X-Signature` using `X-Timestamp` and raw request body.
  - Credits account with 1.5% fee deduction (`credited = paid - round(paid * 0.015)`).
  - Fully idempotent: duplicate events return HTTP 200 without double crediting.

### 7. Deposit Reconciliation
- **`POST /v1/reconciliation/run?older_than_minutes=5`**
  - Scans pending deposits older than N minutes.
  - Queries `provider-mock` via `GET /invoices/{id}` to recover lost webhooks and credit accounts.
  - Returns count of scanned deposits and details of reconciled items.

---

## 🛠 CLI Utilities

### Seed Initial Accounts
```bash
python -m wallet_service.scripts.seed
```

### Run Deposit Reconciliation CLI
```bash
python -m wallet_service.scripts.reconcile --minutes 5
```
