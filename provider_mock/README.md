# Provider Mock Service

In-memory mock of an external payment gateway provider.
Supports invoice creation, payment status simulation, and cryptographically signed HMAC-SHA256 webhooks (including intentional duplicate delivery for idempotency verification).

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PROVIDER_API_KEY` | `mock-provider-key-123` | Bearer token required for API authorization |
| `PROVIDER_WEBHOOK_SECRET` | `mock-webhook-secret-456` | Shared secret key for HMAC-SHA256 webhook signing |
| `PROVIDER_BASE_PAY_URL` | `https://mock-provider.local/pay` | Base URL for generated customer payment links |
| `PROVIDER_PORT` | `8001` | Service HTTP port |
| `PROVIDER_WEBHOOK_TIMEOUT` | `5.0` | Timeout in seconds for outbound webhook requests |

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

### 3. Start the Server
```bash
# From workspace root or provider_mock directory:
uvicorn provider_mock.main:app --reload --port 8001
```

Interactive Swagger UI documentation is available at: [http://localhost:8001/docs](http://localhost:8001/docs).

---

## 🐳 Docker Deployment

```bash
# Build Docker image
docker build -t provider-mock provider_mock/

# Run container
docker run -p 8001:8001 provider-mock
```

---

## 🧪 Testing

```bash
pytest provider_mock/tests -v
```

---

## 📡 API Endpoints

All provider endpoints require the authorization header:
`Authorization: Bearer <PROVIDER_API_KEY>`

### 1. Create Invoice
**`POST /invoices`** (Status: `201 Created`)
```bash
curl -X POST http://localhost:8001/invoices \
  -H "Authorization: Bearer mock-provider-key-123" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "10.00",
    "currency": "USD",
    "external_id": "dep_12345",
    "callback_url": "http://wallet-service:8000/v1/webhooks/provider"
  }'
```
Response:
```json
{
  "invoice_id": "inv_a1b2c3d4e5f67890",
  "status": "pending",
  "pay_url": "https://mock-provider.local/pay/inv_a1b2c3d4e5f67890"
}
```

### 2. Retrieve Invoice State
**`GET /invoices/{invoice_id}`** (Status: `200 OK`)
```bash
curl http://localhost:8001/invoices/inv_a1b2c3d4e5f67890 \
  -H "Authorization: Bearer mock-provider-key-123"
```
Response:
```json
{
  "invoice_id": "inv_a1b2c3d4e5f67890",
  "status": "pending",
  "amount": "10.00",
  "paid_amount": "0.00",
  "currency": "USD",
  "external_id": "dep_12345",
  "callback_url": "http://wallet-service:8000/v1/webhooks/provider",
  "created_at": "2026-10-12T10:00:00+00:00",
  "updated_at": "2026-10-12T10:00:00+00:00"
}
```

### 3. Simulate State Transition & Webhook Delivery
**`POST /invoices/{invoice_id}/simulate`** (Status: `200 OK`)
```bash
curl -X POST http://localhost:8001/invoices/inv_a1b2c3d4e5f67890/simulate \
  -H "Authorization: Bearer mock-provider-key-123" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "paid",
    "paid_amount": "10.00",
    "deliver_webhook": true,
    "duplicate": false
  }'
```
> **Note:** Statuses `paid`, `partially_paid`, and `expired` are terminal. Attempting to transition an invoice once terminal returns **HTTP 409 Conflict**.

---

## 🔒 Webhook Format & HMAC Signature

The provider dispatches a `POST <callback_url>` with:
- **Body**:
  ```json
  {
    "event_id": "evt_9876543210abcdef",
    "invoice_id": "inv_a1b2c3d4e5f67890",
    "status": "paid",
    "paid_amount": "10.00",
    "occurred_at": "2026-10-12T10:05:00+00:00"
  }
  ```
- **Headers**:
  - `X-Timestamp: <unix_epoch_timestamp>`
  - `X-Signature: sha256=<hex_digest>`

**Signature Algorithm**:
$$\text{Signature} = \text{HMAC-SHA256}(\text{secret}, \text{timestamp} + "." + \text{raw\_body})$$
