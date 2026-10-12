# AI Collaboration Notes

This document summarizes the role of AI assistance in designing and implementing the LedgerLite Wallet Service and Payment Provider Mock, adhering to the project requirements.

---

## 1. AI Tools Used & Purpose
- **Gemini 3.8 Flash (via Antigravity / Pair Programming Agent)**:
  - Code generation (scaffolding FastAPI apps, Pydantic v2 schemas, SQLAlchemy 2.0 async models).
  - Test suite generation (unit, edge case, and integration tests across 94 scenarios).
  - Refactoring and documentation assistance.

---

## 2. Division of Responsibility: Human vs. AI

| Area | Human Responsibility | AI Responsibility |
|---|---|---|
| **System Architecture** | Microservice separation, decoupled virtual environments, Docker Compose orchestration, PostgreSQL ACID guarantees. | Scaffolding directory structures, Dockerfile drafting, and config loading. |
| **Financial Ledger Integrity** | Enforcing strict string-to-`Decimal` parsing, half-up rounding rules, deadlock-free alphabetical row locking. | Implementing arithmetic utility functions and unit tests for rounding edge cases. |
| **Dependency Injection & Resources** | Rejecting ad-hoc client/DB creation; mandating FastAPI `Depends()` and pooled connections. | Wiring dependencies into endpoint parameters. |
| **Pagination Strategy** | Explicitly choosing Keyset (cursor-based) pagination over Offset pagination for consistent writes. | Writing the SQL `(created_at, id) < (cursor_date, cursor_id)` filter logic. |
| **Tooling & Library Selection** | Vetoing faulty third-party packages (`slowapi`) in favor of a clean ASGI sliding-window middleware. | Writing initial code drafts and test fixtures. |

---

## 3. Specific AI Flaws & Bugs Caught During Development

### Bug 1: Ad-hoc Socket Spawning vs. Dependency Injection (DI)
- **Problem**: In early service drafts, AI generated endpoints that instantiated a new `httpx.AsyncClient()` inside each request handler (and similarly attempted to create raw database connections on the fly).
- **Impact**: Under high concurrency, opening a new TCP connection and TLS handshake per HTTP call exhausts operating system sockets (`TIME_WAIT` socket starvation), severely degrades throughput, and prevents clean mock injection during automated testing.
- **Correction**: Rejected ad-hoc instantiation. Introduced a shared HTTP client pool managed by the FastAPI `lifespan` context, injected via `Depends(get_provider_client)`, alongside standard `Depends(get_db_session)` session pooling.

### Bug 2: Pydantic Context `ValueError` Crashing JSON Exception Serialization
- **Problem**: When generating custom 422 error handlers for `RequestValidationError`, AI directly passed Pydantic's `exc.errors()` into Starlette's `JSONResponse(content=...)`.
- **Impact**: In Pydantic v2, certain validation failures (such as custom string-to-decimal validators) include Python exception objects (e.g. `ValueError`) inside the `ctx` dictionary. Starlette's JSON encoder failed to serialize these objects, causing internal HTTP 500 crashes instead of uniform HTTP 422 responses.
- **Correction**: Replaced raw dictionary serialization with `fastapi.encoders.jsonable_encoder`, ensuring all nested error contexts are properly sanitized.

### Bug 3: SQLite String Truncation Breaking Keyset Pagination Cursor Equality
- **Problem**: Keyset cursor pagination uses composite tie-breakers `(created_at, id)`. In tests running on SQLite, timestamps defaulted to SQL `CURRENT_TIMESTAMP`, which strips microseconds (`YYYY-MM-DD HH:MM:SS`), while Python `datetime.now(UTC)` generated full microsecond strings.
- **Impact**: Consecutive transactions inserted in the same second resulted in broken pagination ordering and missing records during cursor traversal.
- **Correction**: Standardized model timestamps to use Python-side `datetime.now(UTC)` with full microsecond precision across both SQLite and PostgreSQL.

### Bug 4: SlowAPI Crashing on Pydantic Response Models
- **Problem**: When tasked with rate limiting, AI recommended the widely used `slowapi` library and applied its `@limiter.limit` decorator on routes returning Pydantic models.
- **Impact**: SlowAPI's internal header injection crashed at runtime with `Exception: parameter 'response' must be an instance of starlette.responses.Response` because FastAPI passes Pydantic models to decorators before Starlette wraps them into responses.
- **Correction**: Discarded `slowapi`. Implemented a pure ASGI sliding-window rate limiter middleware (`InMemoryRateLimiter`, ~40 lines) that cleanly handles Pydantic endpoints, exempts webhooks, and injects compliant RFC `Retry-After` headers.

---

## 4. Estimated Time Spent

- **Total Development Time**: **~4.5 hours**
  - **Architecture & Domain Design**: ~0.5 hr (financial rules, state machines, API schema contracts).
  - **Provider Mock (Service A)**: ~1.0 hr (invoices, HMAC webhook signing, simulation endpoints, 24 tests).
  - **Wallet Service (Service B Core)**: ~1.5 hrs (auth, accounts, deposits, deadlock-free transfers, credit purchasing, 70 tests).
  - **Rate Limiting, Pagination & Reconciliation**: ~1.0 hr (ASGI sliding window, keyset cursors, recovery CLI).
  - **Docker Compose, CI & Documentation**: ~0.5 hr (GitHub Actions, multi-stage builds, README, AI_NOTES).
