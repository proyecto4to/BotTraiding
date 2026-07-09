# TradingPlatform

Plataforma de trading algoritmico modular, multi-broker, multi-mercado,
multi-estrategia, multi-IA y multi-usuario. La arquitectura completa,
principios de diseno y contratos entre servicios viven en
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — leerlo antes de tocar
cualquier servicio.

This repository is currently in **Fase 1**: infrastructure scaffolding only.
No trading business logic exists yet (see `docs/ARCHITECTURE.md` section 11).

## Repo layout

```
services/            Python (FastAPI) microservices, one per responsibility
  shared/contracts/   Shared pydantic models + BrokerConnector/Strategy interfaces
  gateway/             AuthN/AuthZ, routing, frontend aggregation
  auth-service/        Users, JWT, MFA, roles, audit
  strategy-engine/     Strategy plugins -> TradeSignal
  risk-engine/         Validates TradeSignal against RiskLimits
  portfolio-engine/    Account state: exposure, margin, PnL, drawdown
  ai-engine/           Market regime, strategy ranking/selection
  execution-engine/    TradeSignal -> Order -> broker submission
  broker-connectors/   BrokerConnector adapters per broker/exchange
  backtester/          Historical simulation
  optimizer/           Parameter search + out-of-sample validation
  paper-trading/       Simulated broker adapter, same execution-engine
  notification-service/  Alerts (email/push/webhook)
  scheduler/           Periodic jobs (retraining, reoptimization)
  trading-engine/      Orchestrates signal -> risk -> portfolio -> execution
frontend/            Next.js + TypeScript dashboard (talks only to gateway)
mobile/              Flutter app skeleton (talks only to gateway)
infra/
  docker/              docker-compose stack + Postgres init.sql
  k8s/                 Base Kustomize manifests (no production tuning yet)
  ci/                  CI-related support files
.github/workflows/    GitHub Actions CI (pytest, lint, docker build per service)
docs/ARCHITECTURE.md  Source of truth for architecture and contracts
```

Every Python service is an independent FastAPI app exposing only `/health`
and `/ready` in Fase 1, depending on the shared `trading_contracts` package
for typed contracts (`TradeSignal`, `RiskDecision`, `Order`, `RiskLimits`,
the `BrokerConnector` interface and the `Strategy` interface). No service
imports another service's code directly — only through these shared,
explicitly defined contracts.

## Running locally

```bash
cd infra/docker
docker compose up --build
```

This brings up Postgres (seeded via `init.sql`), Redis, NATS, Loki,
Prometheus, Grafana, and all 14 Python service containers.

To work on a single service without Docker:

```bash
cd services/<service-name>
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

The frontend (`frontend/`) and mobile app (`mobile/`) are skeletons — install
dependencies (`npm install`, `flutter pub get`) before running them; this
repository does not vendor `node_modules` or Flutter build artifacts.

## Roadmap (Fase 0-15)

Detailed scope for each phase lives in `docs/ARCHITECTURE.md`; Fase 0 (this
document's prerequisites) and the non-negotiable principles are covered
there in full. Summary:

- **Fase 0** — Architecture, contracts, and principles defined (see `docs/ARCHITECTURE.md`).
- **Fase 1** — Infrastructure scaffolding: service skeletons, contracts, CI, docker-compose, base k8s (this repo, current state).
- **Fase 2** — Auth, RBAC, and audit logging implemented end-to-end.
- **Fase 3** — Market data ingestion and broker-connectors stub (simulated) wired to real interfaces.
- **Fase 4** — Strategy plugin loading + first non-trading example strategy.
- **Fase 5** — Risk engine limit enforcement against `RiskLimits`.
- **Fase 6** — Portfolio engine: exposure, margin, correlation, PnL tracking.
- **Fase 7** — Execution engine + paper-trading broker adapter.
- **Fase 8** — Backtester with spread/slippage/commission/latency modeling.
- **Fase 9** — Optimizer with out-of-sample validation gating.
- **Fase 10** — AI engine: market regime detection and strategy ranking.
- **Fase 11** — Notification service and scheduler jobs.
- **Fase 12** — Trading engine orchestration across the full signal-to-execution flow.
- **Fase 13** — Frontend dashboard feature-complete against the gateway API.
- **Fase 14** — Mobile app feature-complete against the gateway API.
- **Fase 15** — Real broker connectors, production k8s tuning, go-live readiness.
