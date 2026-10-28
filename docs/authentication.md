# Authentication and authorization

## Security model

MARGINA currently uses a first-party Flask session adapter so the pilot can be exercised without selecting a hosted identity vendor prematurely. Account and authorization services are separated from routes so a managed OIDC identity adapter can replace password verification later.

- Accounts are provisioned through Flask CLI commands; there is no public registration endpoint.
- Passwords are stored only as Werkzeug scrypt hashes.
- Passwords must contain 12-128 characters by default.
- Login errors do not reveal whether an email exists.
- Five consecutive failures lock an account for 15 minutes by default.
- Successful login clears any previous session and creates a new eight-hour permanent session plus a random CSRF token.
- Session cookies are HTTP-only and `SameSite=Lax`; production startup requires secure cookies and PostgreSQL.
- Authenticated `POST`, `PATCH`, and other mutation requests require `X-CSRF-Token`.
- Account status and `session_version` are checked on every authenticated request.
- Sensitive authenticated responses use `Cache-Control: no-store`.

## Provisioning

Create the organization once on a fresh database:

```powershell
.\venv\Scripts\python.exe -m flask --app wsgi auth create-organization `
  --tenant-id demo-distributor `
  --name "Synthetic Distributor" `
  --currency PKR `
  --timezone Asia/Karachi
```

The existing local database already contains this organization. Create the first unrestricted administrator and finance owner; each command prompts for the password without placing it in shell history:

```powershell
.\venv\Scripts\python.exe -m flask --app wsgi auth create-user `
  --email admin@example.com `
  --tenant-id demo-distributor `
  --role administrator

.\venv\Scripts\python.exe -m flask --app wsgi auth create-user `
  --email finance@example.com `
  --tenant-id demo-distributor `
  --role finance
```

Repeat `--branch "Branch A"` to restrict a membership. Omitting `--branch` means all branches.

## Role policy

| Action | Required role | Branch rule |
| --- | --- | --- |
| Import the synthetic dataset | Administrator | Unrestricted |
| Read import reconciliation | Finance, analyst, or administrator | Unrestricted |
| Read snapshot metadata | Any active business role | Tenant membership required |
| Approve reconciled snapshot | Finance | Unrestricted |
| Publish approved snapshot | Administrator | Unrestricted |
| List/create/update memberships | Administrator | Unrestricted |

The last unrestricted active administrator cannot be disabled, downgraded, or given a restricted branch scope.

An empty `branch_scope` means all branches. A non-empty list is an allowlist. Future branch-specific financial and process routes must call the shared branch authorization function rather than filtering only in the browser.

## Login API

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email":"admin@example.com","password":"..."}
```

The response returns the authenticated user, active memberships, and CSRF token. The browser must retain the HTTP-only session cookie and send the token in `X-CSRF-Token` for mutations.

Additional endpoints:

- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `GET /api/v1/organizations/{tenant_id}/memberships`
- `POST /api/v1/organizations/{tenant_id}/memberships`
- `PATCH /api/v1/organizations/{tenant_id}/memberships/{membership_id}`

The browser login is available at `/login`; successful authentication continues to `/workspace`. The workspace applies role and branch scope on the server before returning published-snapshot analytics. The public `/demo` remains fixed to the isolated synthetic tenant and cannot select a customer organization.

## Current boundary

This is a secure pilot adapter, not enterprise identity. Password reset, email verification, MFA, SSO/OIDC, global/IP rate limiting, and administrative account disabling remain future work. Do not claim enterprise identity compliance until those controls and PostgreSQL RLS are implemented and tested.
