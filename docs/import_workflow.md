# Synthetic CSV import workflow

This implementation is the deterministic import path for the bundled synthetic distributor. It is intentionally not a customer-upload endpoint. All import and snapshot routes now require authenticated organization membership, explicit roles, branch scope, and CSRF protection.

## State flow

1. `POST /api/v1/imports/synthetic` reads the five repository fixtures.
2. Every file is hashed together with its filename to create one dataset identity.
3. Validation checks exact headers, UTF-8 decoding, file/row limits, required values, decimal and UTC timestamp types, single-tenant/currency/timezone policy, unique keys, relationships, event completeness, approved cost categories, and order-to-line control totals.
4. Invalid data with a trustworthy tenant identity creates a `quarantined` import containing structured file, row, field, code, and message errors. No snapshot or analytical rows are created.
5. Valid data is inserted transactionally into a `draft` snapshot. Reconciled control totals are stored on the import batch.
6. A finance actor explicitly approves the snapshot.
7. An approved snapshot can be published. A previous published snapshot for that tenant is marked `superseded` in the same transaction.

Only published snapshots are exposed to normal business reporting. The recruiter demo is fixed to the isolated `demo-distributor` tenant and reads its latest published database snapshot through the shared analytics service.

## Idempotency

`tenant_id + SHA-256(dataset filenames and bytes)` is unique. Repeating an identical import returns the original import and snapshot IDs, increments `duplicate_count`, and inserts no duplicate business rows. Database uniqueness remains the final concurrency guard.

Corrections must change the CSV bytes and therefore create a new import and snapshot rather than silently rewriting the previous snapshot.

## Manual API walkthrough

Start Flask and provision an administrator and finance user as described in `docs/authentication.md`. Then run these PowerShell requests:

```powershell
$adminBody = @{ email = "admin@example.com"; password = "your-password" } | ConvertTo-Json
$admin = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/v1/auth/login `
  -ContentType application/json `
  -Body $adminBody `
  -SessionVariable AdminSession

$adminHeaders = @{ "X-CSRF-Token" = $admin.csrf_token }
$import = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/v1/imports/synthetic `
  -WebSession $AdminSession `
  -Headers $adminHeaders
$import.import.control_totals
$snapshotId = $import.snapshot.snapshot_id

$financeBody = @{ email = "finance@example.com"; password = "your-password" } | ConvertTo-Json
$finance = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/v1/auth/login `
  -ContentType application/json `
  -Body $financeBody `
  -SessionVariable FinanceSession

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:5000/api/v1/snapshots/$snapshotId/approve" `
  -WebSession $FinanceSession `
  -Headers @{ "X-CSRF-Token" = $finance.csrf_token }

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:5000/api/v1/snapshots/$snapshotId/publish" `
  -WebSession $AdminSession `
  -Headers $adminHeaders
```

The audit actor is derived from the authenticated session and cannot be supplied in request JSON.
