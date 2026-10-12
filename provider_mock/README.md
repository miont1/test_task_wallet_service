# Provider Mock Service

Імітація зовнішнього платіжного провайдера.
Зберігає інвойси в оперативній пам'яті (in-memory) та підтримує створення рахунків, симуляцію оплати й надсилання криптографічно підписаних вебхуків (включаючи дублікати для тестування ідемпотентності).

---

## ⚙️ Змінні оточення

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `PROVIDER_API_KEY` | `mock-provider-key-123` | Bearer токен для викликів до провайдера |
| `PROVIDER_WEBHOOK_SECRET` | `mock-webhook-secret-456` | Секрет для підпису HMAC-SHA256 вебхуків |
| `PROVIDER_BASE_PAY_URL` | `https://mock-provider.local/pay` | Базовий URL посилань на оплату |
| `PROVIDER_PORT` | `8001` | Порт сервісу |
| `PROVIDER_WEBHOOK_TIMEOUT` | `5.0` | Таймаут надсилання вебхука (в секундах) |

---

## 🚀 Запуск локально

1. Створення та активація віртуального оточення:
```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

2. Встановлення залежностей:
```bash
pip install -r requirements.txt
```

3. Запуск сервера:
```bash
# З кореня репозиторію:
uvicorn provider_mock.main:app --reload --port 8001
```

Інтерактивна документація Swagger доступна за адресою: [http://localhost:8001/docs](http://localhost:8001/docs).

---

## 🐳 Запуск у Docker

```bash
# Збірка образу
docker build -t provider-mock provider_mock/

# Запуск контейнера
docker run -p 8001:8001 provider-mock
```

---

## 🧪 Запуск тестів

```bash
pytest provider_mock/tests -v
```

---

## 📡 API Ендпоінти

Усі запити до провайдера вимагають заголовок:
`Authorization: Bearer <PROVIDER_API_KEY>`

### 1. Створення інвойсу
**`POST /invoices`** (Статус: 201 Created)
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
Відповідь:
```json
{
  "invoice_id": "inv_a1b2c3d4e5f67890",
  "status": "pending",
  "pay_url": "https://mock-provider.local/pay/inv_a1b2c3d4e5f67890"
}
```

### 2. Отримання стану інвойсу
**`GET /invoices/{invoice_id}`** (Статус: 200 OK)
```bash
curl http://localhost:8001/invoices/inv_a1b2c3d4e5f67890 \
  -H "Authorization: Bearer mock-provider-key-123"
```
Відповідь:
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

### 3. Симуляція зміни стану та відправка вебхука
**`POST /invoices/{invoice_id}/simulate`** (Статус: 200 OK)
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
> **Увага:** Статуси `paid`, `partially_paid` та `expired` є фінальними. Спроба повторно змінити стан інвойсу поверне **HTTP 409 Conflict**.

---

## 🔒 Формат вебхука та підпис

Провайдер відправляє `POST <callback_url>` із:
- **Тілом**:
  ```json
  {
    "event_id": "evt_9876543210abcdef",
    "invoice_id": "inv_a1b2c3d4e5f67890",
    "status": "paid",
    "paid_amount": "10.00",
    "occurred_at": "2026-10-12T10:05:00+00:00"
  }
  ```
- **Заголовками**:
  - `X-Timestamp: <unix_timestamp>`
  - `X-Signature: sha256=<hex_digest>`

**Формула підпису**:
$$\text{Signature} = \text{HMAC-SHA256}(\text{secret}, \text{timestamp} + "." + \text{raw\_body})$$
