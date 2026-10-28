# MARGINA

MARGINA links order-level financial evidence with order-to-dispatch process events. This repository is the Flask implementation of the functional-pilot proposal.

## Current foundation

- Flask application factory with environment validation and JSON error handling
- PostgreSQL-ready SQLAlchemy and migration integration
- health and database-readiness endpoints
- versioned financial metric definitions using `Decimal`
- deterministic directly-follows process analysis
- public `/demo` with computed synthetic metrics, linked source orders, branch filters, and a session-scoped shipping scenario
- five proposal-aligned UTF-8 synthetic CSV fixtures with documented metric and workflow policies
- validated, reconciled, idempotent synthetic imports with approval-gated snapshot publication
- secure pilot authentication, organization memberships, role separation, branch scopes, and CSRF protection
- responsive login, recruiter dashboard, and role-aware business workspace backed by the published snapshot
- unit and API tests

This is an implemented demo foundation, not the completed 20-week pilot. Authentication, tenant-aware imports, reconciliation, published snapshots, and role-aware dashboards are implemented. Investigations, the bounded AI assistant, exports, customer upload onboarding, and production operations remain subsequent roadmap work.

## Local setup

The repository includes a `venv` directory. Install the declared packages and run the server:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m flask --app wsgi run --debug
```

Open `http://127.0.0.1:5000/demo` for the public synthetic recruiter view or `http://127.0.0.1:5000/login` for the authenticated business workspace. Do not use Flask's development server in production; `waitress-serve --call margina:create_app` is included for a production-style local process.

## Configuration

Configuration is read from environment variables. A real `.env` file is intentionally not committed because it may contain secrets. Copy [`.env.example`](.env.example) to `.env` for local configuration and replace its placeholder secret. Production hosts should store the same values in their encrypted environment settings.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | production only | `development` | Enables production validation |
| `SECRET_KEY` | production only | development-only value | Signs demo session state |
| `DATABASE_URL` | production only | local SQLite database | PostgreSQL connection URL in production |
| `LOG_LEVEL` | no | `INFO` | Application logging level |
| `REPORTING_TIMEZONE` | no | `Asia/Karachi` | Presentation timezone |
| `DEMO_ENABLED` | no | `true` | Enables the public synthetic demo |
| `SESSION_COOKIE_SECURE` | production | enabled in production | Requires HTTPS-only session cookies |
| `SESSION_HOURS` | no | `8` | Authenticated session lifetime |
| `MAX_LOGIN_ATTEMPTS` | no | `5` | Failures before temporary account lockout |
| `AUTH_LOCK_MINUTES` | no | `15` | Temporary account lock duration |
| `PASSWORD_MIN_LENGTH` | no | `12` | Minimum provisioned password length |

Generate a local secret without committing it:

```powershell
Copy-Item .env.example .env
.\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into the local `.env` file. Never paste production secrets into source code, GitHub, screenshots, or logs.

When using Flask's `MARGINA_` config prefix, values such as `MARGINA_DEMO_ENABLED=false` override loaded configuration.

## Checks

```powershell
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m ruff check .
```

## API endpoints implemented

- `GET /api/v1/health`
- `GET /api/v1/ready`
- `GET /api/v1/metrics/definitions`
- `GET /api/v1/demo/summary?branch=Branch%20A`
- `GET /api/v1/demo/orders?branch=Branch%20A`
- `GET /api/v1/demo/process`
- `POST /api/v1/demo/scenarios/shipping`
- `POST /api/v1/demo/reset`
- `POST /api/v1/imports/synthetic`
- `GET /api/v1/imports/{import_id}`
- `GET /api/v1/snapshots/{snapshot_id}`
- `POST /api/v1/snapshots/{snapshot_id}/approve`
- `POST /api/v1/snapshots/{snapshot_id}/publish`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `GET|POST /api/v1/organizations/{tenant_id}/memberships`
- `PATCH /api/v1/organizations/{tenant_id}/memberships/{membership_id}`
- `GET /api/v1/organizations/{tenant_id}/dashboard/summary`
- `GET /api/v1/organizations/{tenant_id}/dashboard/orders`
- `GET /api/v1/organizations/{tenant_id}/dashboard/process`

All demo records are synthetic. Scenario output is an estimate based on explicit assumptions and is not presented as proven profit.

## Synthetic import fixtures

The five files in [`sample_data/synthetic`](sample_data/synthetic) cover orders, lines, costs, returns, and process events. Their schema, approved assumptions, control totals, and deliberately seeded investigation signals are documented in [`docs/synthetic_data_spec.md`](docs/synthetic_data_spec.md).

The validation, reconciliation, idempotency, approval, and publication lifecycle is documented in [`docs/import_workflow.md`](docs/import_workflow.md). These routes are currently restricted by design to the bundled synthetic fixture; authenticated customer uploads remain a later phase.

Account provisioning, session security, CSRF usage, roles, and branch authorization are documented in [`docs/authentication.md`](docs/authentication.md). There is deliberately no public registration endpoint.

The recruiter dashboard and authenticated workspace use the same published-snapshot analytics service. Finance and analyst memberships can inspect authorized financial evidence; operations and administrator memberships receive process/system views without silently inheriting financial access.

## AI and external services

The current demo does **not** call an AI provider. Its metrics, process map, reconciliation, and scenario calculations are deterministic and remain available without an AI API. The proposal's bounded, evidence-linked assistant is a later module and must use approved read-only tools rather than querying tables or inventing values directly.

No third-party API key is required for the current local recruiter demo. A production deployment requires a PostgreSQL `DATABASE_URL` and secure `SECRET_KEY`. Adding the proposed assistant will require selecting a hosted model provider and adding its server-side API key; no provider has been selected or falsely represented as connected.

## Hosting

GitHub Pages cannot run this Flask application or its database because Pages serves static files. Use GitHub for source control and a Python web host such as Render for the Flask service, with managed PostgreSQL for durable production data. The included `Procfile` starts the app with Waitress and the host-provided `PORT`.

Production deployment checklist:

1. Provision managed PostgreSQL and configure `DATABASE_URL`.
2. Set `APP_ENV=production`, a strong generated `SECRET_KEY`, and `SESSION_COOKIE_SECURE=true`.
3. Install from `requirements.txt` and run `flask --app wsgi db upgrade` as a controlled release step.
4. Start with the `Procfile` command.
5. Create production users through the authenticated CLI process and import, approve, and publish the intended synthetic or customer snapshot.
6. Configure HTTPS, backups, database retention, monitoring, and a health check on `/api/v1/ready`.
