# Security & Data Governance

| Control | Implementation |
|---|---|
| Authentication | `POST /api/v1/auth/login` → JWT (HS256, 8 h default, `JWT_SECRET` ≥ 32 chars enforced at start-up). Passwords are hashed with scrypt (N=2¹⁴, salted) and must be at least 10 characters. 5 failed attempts lock the account for 15 min. Disabled accounts are rejected on every request. |
| Session storage | The token is kept in `sessionStorage` (cleared when the tab closes). No credentials or keys exist in any frontend file. |
| RBAC | `admin`, `data_manager`, `analyst`, `viewer` with permissions `dashboard:read`, `financial:read`, `chat:use`, `export:run`, `ingestion:read/write`, `users:manage`, `audit:read`, `reconciliation:read`. These are enforced server-side on every endpoint. |
| Sensitive datasets | Budget and unit cost need `financial:read`. For viewers they are `null` in every payload and the financial module returns 403. |
| Data scoping | `allowed_divisions` per user is intersected with every filter in SQL, including bootstrap, exports and chatbot. Tested: a Pune-only user cannot read Nagpur by passing `division=Nagpur`. |
| Read-only analytics | Every dashboard, analytics and chatbot query runs as `medd_readonly` with `default_transaction_read_only=on`, a 15 s statement timeout and a 5 s timeout for the chatbot. |
| SQL injection | All values are bound parameters (`= ANY(:param)`, `ILIKE :q`). Sort keys and levels are allow-listed. The chatbot never generates SQL from text. Tested with injection payloads. |
| Uploads | Extension allow-list, size limit (`MAX_UPLOAD_MB`), filename sanitised, written atomically, never executed. |
| Stored XSS | Names are neutralised at ingestion. The 2.0 code escapes output and the CSP restricts scripts to same origin. |
| HTTP headers | CSP, X-Frame-Options, nosniff, Referrer-Policy, `Cache-Control: no-store` on the API. With `FORCE_HTTPS=true`: HSTS and an HTTPS redirect. |
| HTTPS deployment | Run behind IIS, nginx or Apache with TLS. Set `FORCE_HTTPS=true`, and set `CORS_ORIGINS` only if the frontend is hosted on another origin. |
| Secrets | Only in `backend/.env` (git-ignored). `.env.example` contains placeholders only. |
| Audit | `audit.audit_log` (append-only, enforced by a trigger) records logins, failed logins, uploads, every ingestion result, rollbacks, exports, chatbot questions and user changes. `audit.line_item_history` holds row-level old→new values per file. |
| LLM (optional) | Off by default. When enabled it receives only already-computed, permission-filtered results and may only rephrase them. Numbers always come from SQL. |

Known limitation: the SSE stream passes the token as a query parameter, because EventSource cannot set headers. Make sure reverse-proxy access logs do not store query strings, or terminate SSE at the proxy.
