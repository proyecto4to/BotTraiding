# Escalabilidad — TradingPlatform (Fase 15)

How the platform scales from one bot to hundreds of bots/users, what state
lives where today, and what must move before scaling certain services.

## 1. The model: stateless services over shared state

Every service is a FastAPI app that keeps durable state in **Postgres**
(per-service tables, Alembic-migrated), hot/shared state in **Redis**
(reserved for rate limiting/sessions/cache), and communicates asynchronously
over **NATS**. A request can land on any replica of a stateless service and
produce the same answer, so horizontal scaling is "add replicas":

- `infra/k8s/*.yaml` — every Deployment now carries modest resource
  requests/limits (100m CPU / 256Mi request, 500m / 512Mi limit) so the
  scheduler can bin-pack and the HPA has a CPU baseline.
- `infra/k8s/hpa.yaml` — `autoscaling/v2` HPAs (min 1, max 5, target 70% CPU)
  for the stateless services.

## 2. What state lives where

### Safe at N replicas today

| Service | Why |
|---|---|
| strategy-engine | strategies/configs in Postgres; registry synced from code at startup |
| risk-engine | limits, risk_events, circuit breakers in Postgres; validate() is pure per-request |
| portfolio-engine | account state in Postgres |
| execution-engine | executions/child orders/reports in Postgres; transports are per-request HTTP |
| paper-trading | simulated accounts/orders in Postgres |
| backtester | runs/results in Postgres; each run is a self-contained computation |
| optimizer | runs/results in Postgres; calls backtester over HTTP |
| ai-engine | recommendations/regimes in Postgres |
| notification-service, trading-engine | no local state (skeleton orchestrator) |

### In-memory state that must move to Redis (or equivalent) before real scaling

| Service | In-memory state | Consequence at N replicas | Fix |
|---|---|---|---|
| gateway | token-bucket rate limiter (`app/rate_limit.py`) | limit becomes ~N× the configured rate (per replica) | Redis token bucket keyed by user/IP |
| broker-connectors | connector registry + credential store (`app/registry.py`, `app/credential_store.py`); live broker sessions | a `connect` on replica A is invisible to replica B; `place/cancel` 409s unless routed to the owning replica | credentials in Vault/KMS-backed store, session ownership in Redis + sticky routing, or one connector pool per broker account |
| scheduler | in-process APScheduler cron | every job fires N times | keep single replica (no HPA on purpose), or distributed locks / leader election |
| auth-service | none found (users/refresh tokens/audit in Postgres, OAuth state client-side) | believed safe, but unverified under concurrent token revocation — HPA deferred, manual replicas fine | load-test, then add HPA |

The gateway and broker-connectors DO have HPAs (they are CPU-bound and mostly
stateless); the caveats above are about correctness of the rate limit and of
live broker sessions, and are annotated in `hpa.yaml`.

## 3. Path to hundreds of bots/users

1. **Reads scale first.** Dashboard/API traffic fans out through the gateway
   to stateless services — HPAs already cover this.
2. **Signal→order flow scales by account.** Every pipeline step is keyed by
   `account_id`; NATS subjects can be partitioned (queue groups) so multiple
   risk/execution replicas consume disjoint accounts without coordination.
3. **Move the three in-memory pieces to Redis** (rate limiter, broker session
   registry, scheduler locks). After that, `maxReplicas` is a dial, not a
   redesign.
4. **Postgres is the eventual bottleneck**: per-service tables already allow
   splitting into per-service databases; read replicas for the dashboards;
   partition `risk_events`/`executions` by month if audit volume grows.
5. **Market data fan-out** (future work): one ingest per symbol feed, publish
   ticks/bars on NATS; strategies subscribe — bots added without new feeds.

## 4. Operational notes

- All 14 services expose `/metrics`; per-replica utilization is visible in
  Grafana ("TradingPlatform Overview") before and after scaling events.
- `scheduler` and `auth-service` deliberately have **no HPA** — reasons are
  in comments in their manifests and in the table above.
- Compose (`infra/docker/`) remains the single-node dev profile; Kustomize
  (`infra/k8s/`) is the scalable profile. Production overlays (secrets,
  ingress, TLS, per-env tuning) are still future work.
