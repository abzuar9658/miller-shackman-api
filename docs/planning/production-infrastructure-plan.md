# Production Infrastructure Plan

Date: 2026-08-14
Status: Approved direction; DNS delegation requested from Luxury Presence.

## 1. Locked decisions

| Decision | Value |
| --- | --- |
| Cloud | AWS (admin access available) |
| Shape | Option A: single EC2 instance running Docker Compose |
| Environments | Production only |
| Frontend hosting | S3 + CloudFront |
| Email provider (prod) | Mailgun (outbound, inbound routes, delivery webhooks) |
| SMS provider (prod) | Twilio (pending A2P 10DLC approval before automated sends) |
| CI/CD trigger | Every commit to `main` in either repo (PR merge or direct push) |
| Region | `us-east-1` (also required for the CloudFront ACM certificate) |
| Domain | `millerschackman.com` (client's existing domain; registrar Namecheap, DNS on Cloudflare managed by Luxury Presence) |

## 1a. Domain model: subdomain delegation

The root domain is not ours to manage — the client's website (Luxury
Presence), Google Workspace email, and an existing `mail.millerschackman.com`
record all live in a Cloudflare zone LP controls. Instead of individual
record requests, four subdomains are delegated once via NS records to
Route 53 hosted zones in our AWS account:

| Subdomain | Purpose |
| --- | --- |
| `app.millerschackman.com` | Frontend (CloudFront) |
| `api.millerschackman.com` | API + all provider webhooks |
| `mg.millerschackman.com` | Mailgun outbound sending domain (`mail.` was already in use) |
| `inbound.millerschackman.com` | Mailgun inbound reply routing (MX) |

After delegation we manage all records (DKIM, ACM validation, aliases)
without further LP involvement. Root domain, `www`, Google Workspace MX,
and the existing `mail.` record are never touched. Status:

- [x] Four Route 53 public hosted zones created
- [x] Delegation email with the 16 NS values sent to Luxury Presence
- [ ] Delegation confirmed live (`dig NS app.millerschackman.com` returns awsdns servers)

## 2. Architecture overview

```
              Cloudflare (LP-managed root zone)
                NS delegation of 4 subdomains
                             |
              Route 53 (4 hosted zones, our AWS account)
                             |
        +--------------------+---------------------------+
        |                    |                           |
  app.millerschackman  api.millerschackman     mg./inbound.millerschackman
  CloudFront + S3      EC2 (Elastic IP)        Mailgun (DNS records only)
  (static Vite build)  Caddy (TLS) -> compose:
                                 api (uvicorn)
                                 9 worker processes
                                 postgres (pgvector)
                                 rabbitmq / redis
                                 temporal + temporal-postgres
                                 prometheus / grafana (private)
```

- One Docker image (existing `Dockerfile`) provides the API and all worker
  entry points; images are stored in ECR and pulled by the instance.
- Postgres on the instance is the source of truth; nightly `pg_dump` is
  shipped to a dedicated backups S3 bucket with lifecycle retention.
- External SaaS (FUB, OpenRouter/Bedrock, Twilio, Mailgun) needs only
  secrets and webhook URLs pointing at `api.millerschackman.com`.

## 3. AWS resource inventory

| Resource | Purpose | Notes |
| --- | --- | --- |
| EC2 `t3.large` (2 vCPU / 8 GB, 60 GB gp3) | Runs `compose.prod.yaml` | Ubuntu 24.04 LTS; resizable without re-provisioning |
| Elastic IP | Stable address for `api.millerschackman.com` | Attach before creating DNS records |
| Security group | Inbound 80/443 from world; 22 restricted (or SSM-only) | No DB/broker/Temporal ports exposed |
| EC2 instance role | S3 (app bucket + backups bucket), Bedrock invoke, ECR pull, SSM | No long-lived AWS keys on the box |
| ECR repository `miller-schackman-api` | API/worker image | Tag with git SHA + `latest` |
| S3 bucket (app storage) | Existing `STORAGE_PROVIDER=s3` target | Private, SSE-S3 |
| S3 bucket (frontend) | CloudFront origin | Private + Origin Access Control |
| S3 bucket (backups) | Nightly `pg_dump` archives | Lifecycle: expire after 35 days; versioning on |
| CloudFront distribution | Serves `app.millerschackman.com` | SPA: 403/404 → `/index.html`; HTTP→HTTPS redirect |
| ACM certificate (`us-east-1`) | `app.millerschackman.com` for CloudFront | DNS-validated via Route 53 |
| Route 53 hosted zones ×4 | `app.` / `api.` / `mg.` / `inbound.` records (section 4) | Created; delegated via NS records in the LP Cloudflare zone |
| IAM user `ci-deploy` | GitHub Actions credentials | Scoped: ECR push, S3 sync (frontend), CloudFront invalidation, SSM SendCommand to the instance |

TLS for `api.millerschackman.com` is handled by Caddy on the instance via
Let's Encrypt — no ALB or ACM certificate needed for the API host.

## 4. DNS records (each in its own Route 53 hosted zone)

| Record | Zone | Type | Value | Purpose |
| --- | --- | --- | --- | --- |
| `app.millerschackman.com` | `app.` | A (alias) | CloudFront distribution | Frontend |
| `api.millerschackman.com` | `api.` | A | Elastic IP | API + all webhooks |
| `mg.millerschackman.com` | `mg.` | CNAME/TXT ×2–3 | Provided by Mailgun | DKIM/tracking for outbound sending domain |
| `mg.millerschackman.com` | `mg.` | TXT | Provided by Mailgun | SPF |
| `_dmarc.mg.millerschackman.com` | `mg.` | TXT | `v=DMARC1; p=none; rua=mailto:<monitoring>` | DMARC on our sending subdomain; tighten to `p=quarantine` after clean weeks |
| `inbound.millerschackman.com` | `inbound.` | MX ×2 | `mxa.mailgun.org`, `mxb.mailgun.org` (prio 10) | Inbound reply routing |

The root `_dmarc.millerschackman.com` (`p=none`) stays under LP's control
and is never modified; our subdomain DMARC record lives entirely in the
delegated `mg.` zone.

## 5. `compose.prod.yaml` specification

New file in `miller-schackman-api/`, derived from `compose.yaml` with these
differences:

**Services (all `restart: unless-stopped`, images from ECR, no `build:`):**

- `caddy` — terminates TLS for `api.millerschackman.com`, reverse-proxies to `api:8000`.
  Only service publishing host ports (80/443).
- `migrate` — `alembic upgrade head`, runs to completion before app services.
- `api` — uvicorn, no `--reload`, internal port only.
- One service per worker: `temporal-worker`, `temporal-signal-dispatcher`,
  `outbound-send-dispatcher`, `outbox-publisher`, `crm-sync-worker`,
  `crm-sync-scheduler`, `crm-webhook-retry-worker`,
  `crm-history-import-worker`, `inbound-message-worker`. Each gets its own
  container so restarts/logs/resource caps are per-process.
- `postgres` (pgvector/pg16), `rabbitmq`, `redis`, `temporal`,
  `temporal-postgres`, `temporal-ui` — internal network only; no host port
  mappings. Strong passwords from the env file (no `guest:guest`,
  no `postgres:postgres`).
- `prometheus`, `grafana` — bound to localhost or internal only; access via
  SSM port-forward. Grafana anonymous auth disabled in prod.
- Backups run from the host crontab via `scripts/prod_backup.sh` (nightly
  `pg_dump | gzip | aws s3 cp` for both app and Temporal databases, using
  the instance role — no AWS keys involved).

**Excluded from prod:** `cloudbeaver`, `mailpit` (dev-only tools).

**Key environment values (prod `.env` on the instance, mode 600):**

- `ENVIRONMENT=production`, `DEBUG=false`
- `FRONTEND_APP_BASE_URL=https://app.millerschackman.com`
- `ALLOWED_ORIGINS=["https://app.millerschackman.com"]`
- `EMAIL_PROVIDER=mailgun`, `SMS_PROVIDER=twilio`
- Real secrets: `AUTH_JWT_SECRET`, `FUB_API_KEY`, `FUB_SYSTEM_KEY`,
  `OPENROUTER_API_KEY`, `TWILIO_*`, `MAILGUN_API_KEY`,
  `MAILGUN_DOMAIN=mg.millerschackman.com`,
  `MAILGUN_WEBHOOK_SIGNING_KEY`, DB/RabbitMQ passwords
- S3/Bedrock credentials left empty → instance role via default chain
- Compose-level values consumed by `compose.prod.yaml` itself (also in the
  same `.env`): `API_IMAGE` (full ECR image ref — CI rewrites this line on
  each deploy), `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`,
  `RABBITMQ_USER`/`RABBITMQ_PASSWORD`, `TEMPORAL_POSTGRES_PASSWORD`,
  `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`

## 6. CI/CD pipelines

Both repos: GitHub Actions, triggered on push to `main`.

**`miller-schackman-api` — `.github/workflows/deploy.yml`:**

1. `check` job: `uv sync` → `ruff check .` → `mypy app tests` → `pytest`
   (Postgres service container for the persistence tests).
2. `build` job (needs check): build image, tag `git-sha` + `latest`, push to ECR.
3. `deploy` job (needs build): via SSM SendCommand on the instance —
   `docker compose pull && docker compose up -d --remove-orphans`
   (the `migrate` service applies Alembic migrations before app services
   start). Post-deploy: curl the API health endpoint; fail loudly if unhealthy.

**`miller-schackman-web` — `.github/workflows/deploy.yml`:**

1. `check` job: `pnpm install --frozen-lockfile` → `pnpm check`.
2. `deploy` job: `pnpm build` with `VITE_API_BASE_URL=https://api.millerschackman.com`
   → `aws s3 sync dist/ s3://<frontend-bucket> --delete`
   → CloudFront invalidation (`/*`).

GitHub repository secrets (values never in the repo): `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` (the `ci-deploy` user), `AWS_REGION`,
`ECR_REPOSITORY`, `EC2_INSTANCE_ID`, `FRONTEND_BUCKET`,
`CLOUDFRONT_DISTRIBUTION_ID`, `VITE_API_BASE_URL`.

## 7. Mailgun production setup

1. Create Mailgun account (or upgrade the sandbox) on a paid plan
   (inbound routes require it).
2. Add domain `mg.millerschackman.com`; publish the DKIM/SPF/tracking
   records it supplies into the `mg.` Route 53 zone; wait for verification.
3. Add `inbound.millerschackman.com` MX records; create a Mailgun Route:
   match recipient `.*@inbound.millerschackman.com` → forward to
   `https://api.millerschackman.com/api/v1/webhooks/mailgun/inbound-messages/{workspace_id}`.
4. Configure delivery/bounce webhooks to the Mailgun events webhook route;
   record the webhook signing key into the prod env.
5. Warm-up: ramp sending volume gradually over 2–4 weeks; do not enroll the
   full dormant backlog on day one. Keep DMARC at `p=none` while monitoring.

## 8. Backups and restore

- Nightly 03:00 UTC: `pg_dump -Fc` of `miller_schackman` and `temporal`
  databases → gzip → `s3://<backups-bucket>/postgres/YYYY-MM-DD/`.
- Retention: 35 days via bucket lifecycle; bucket versioning enabled.
- Restore runbook: provision instance → `docker compose up postgres` →
  `pg_restore` latest dump → start remaining services → repoint DNS.
- Quarterly: test-restore a dump into a scratch container and run a row-count
  sanity check (documented as an operational task, not automated in V1).

## 9. Provisioning checklist (execution order)

1. [x] Domain: four Route 53 hosted zones created; NS delegation requested
       from Luxury Presence (verify with `dig NS app.millerschackman.com`).
2. [ ] Create S3 buckets (app storage, frontend, backups) + ECR repository.
3. [ ] Create IAM: instance role, `ci-deploy` user with scoped policy.
4. [ ] Launch EC2 (`t3.large`, Ubuntu 24.04, 60 GB gp3, instance role,
       security group); attach Elastic IP; install Docker + compose plugin.
5. [ ] Create `api.millerschackman.com` A record → Elastic IP.
6. [x] Author `compose.prod.yaml` + `docker/caddy/Caddyfile` +
       `scripts/prod_backup.sh` in the API repo (code task).
7. [ ] Write prod `.env` on the instance (secrets gathered securely, never
       committed); first manual `docker compose up -d`; verify health + TLS.
8. [ ] ACM certificate (`us-east-1`) for `app.millerschackman.com`;
       CloudFront distribution with S3 OAC origin; `app.` alias record.
9. [x] GitHub Actions workflows authored in both repos
       (`.github/workflows/deploy.yml`); still to do: set repo secrets and
       verify a full pipeline run deploys end to end.
10. [ ] Mailgun domain + inbound + webhooks (section 7).
11. [ ] Twilio: purchase number, start A2P 10DLC registration, point SMS
       webhook to `api.millerschackman.com`; SMS stays non-automated until
       `approved`.
12. [ ] FUB: register system + webhooks against `api.millerschackman.com`;
       set `FUB_SYSTEM_KEY`.
13. [ ] Verify backup job ran and a dump object exists in S3.
14. [ ] Smoke test: sign-in from `app.millerschackman.com`, CRM sync,
       sink-free email send through Mailgun to a controlled inbox, inbound
       reply roundtrip.

## 10. Explicitly out of scope (V1)

- Staging environment, multi-AZ/high availability, managed RDS/MQ/Temporal
  Cloud (the per-service compose layout keeps each liftable later).
- Amazon SES (violates the no-raw-MIME-parsing constraint for inbound;
  possible later as an outbound-only adapter behind `EmailProvider`).
- Autoscaling, Kubernetes, Terraform (console/CLI provisioning is acceptable
  at this scale; revisit if a second environment is added).
