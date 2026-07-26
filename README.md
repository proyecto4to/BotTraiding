# TradingPlatform

Plataforma de trading algoritmico modular, multi-broker, multi-mercado,
multi-estrategia, multi-IA y multi-usuario. La arquitectura completa,
principios de diseno y contratos entre servicios viven en
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — leerlo antes de tocar
cualquier servicio. Cómo escala (y qué falta para escalar más) está en
[`docs/SCALABILITY.md`](docs/SCALABILITY.md).

**Estado: Fases 0–15 implementadas** (ver tabla más abajo). Todo el flujo
señal → riesgo → portafolio → ejecución funciona en modo paper. El modo live
está apagado por defecto y necesita tres cosas independientes para activarse:
`EXECUTION_LIVE_ENABLED=true` (default `false`), un JWT de administrador en
cada orden live, y superar todos los gates de promoción paper→live.

## Repo layout

```
services/              Python (FastAPI) microservices, one per responsibility
  shared/contracts/     trading_contracts: pydantic models + BrokerConnector/
                        Strategy interfaces + DB-free JWT helpers
  shared/strategies/    trading_strategies: built-in strategy plugins
  gateway/              AuthN/AuthZ, rate limiting, /api/* reverse proxy,
                        market/symbol config, audit log
  auth-service/         Users, JWT, Google OAuth, MFA (TOTP), roles, audit
  strategy-engine/      Strategy plugins -> TradeSignal (registry + DB sync)
  risk-engine/          TradeSignal validation, sizing, circuit breakers,
                        risk_events feed
  portfolio-engine/     Account state: exposure, margin, PnL, drawdown
  ai-engine/            Market regime, strategy ranking, underperformance
  execution-engine/     Order slicing, retries, paper/live transports
  broker-connectors/    8 HTTP broker adapters + MetaTrader5 (place/cancel/
                        positions/account/historical), in-memory credentials
  backtester/           Historical simulation (spread/slippage/commission/latency)
  optimizer/            Parameter search + out-of-sample promotion gate
  paper-trading/        Simulated broker with configurable fill model
  notification-service/ Alerts skeleton (NATS consumer future work)
  scheduler/            APScheduler cron: reoptimize, regime refresh, health pings
  trading-engine/       Orchestrator skeleton (flow lives in the services)
frontend/              Next.js 14 dashboard (talks ONLY to the gateway)
mobile/                Flutter app skeleton (talks only to the gateway)
infra/
  docker/               docker-compose stack, init.sql, prometheus.yml,
                        grafana provisioning + dashboard, promtail -> Loki
                        (see infra/docker/README-observability.md)
  k8s/                  Kustomize manifests: resources/limits on every
                        Deployment + HPAs for stateless services (hpa.yaml)
.github/workflows/     CI: pytest + ruff + docker build per service
docs/                  ARCHITECTURE.md (source of truth), SCALABILITY.md
```

## Quickstart (docker compose)

```bash
cp infra/docker/.env.example infra/docker/.env   # set JWT_SECRET etc.
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up --build
```

Then:

- Frontend: <http://localhost:3000> (register a user, then log in)
- Gateway API: <http://localhost:8000> (everything under `/api/*`)
- Grafana: <http://localhost:3001> (admin/admin — "TradingPlatform Overview"
  dashboard is pre-provisioned; Prometheus + Loki datasources included)
- Prometheus: <http://localhost:9090>

Services with persistence run their Alembic migrations automatically at
container start. Every service exposes `/health`, `/ready` and `/metrics`.

To work on a single service without Docker:

```bash
cd services/<service-name>
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

Frontend: `cd frontend && npm install && npm run dev` (set
`NEXT_PUBLIC_GATEWAY_URL` if the gateway is not on `http://localhost:8000`).

## Estado por fase

| Fase | Alcance | Estado | Tests |
|---|---|---|---|
| 0 | Arquitectura, contratos, principios (`docs/ARCHITECTURE.md`) | ✅ | — |
| 1 | Scaffolding: 14 servicios, contratos, CI, compose, k8s base | ✅ | health tests (notification 2, trading-engine 2) |
| 2 | auth-service: registro, login, JWT+refresh, Google OAuth, MFA, roles, auditoría | ✅ | 24 |
| 3 | broker-connectors: 8 adapters HTTP + MT5, registry, rate limit, reconexión, cancel | ✅ | 72 |
| 4 | gateway: mercados/símbolos, reverse proxy `/api/*`, rate limiting, auditoría | ✅ | 59 |
| 5–6 | strategy-engine: plugins, sync a DB, configs por estrategia, evaluación | ✅ | 135 |
| 7 | risk-engine + portfolio-engine: límites, sizing, circuit breakers, exposición/PnL | ✅ | 82 + 22 |
| 8 | backtester: simulación con spread/slippage/comisión/latencia | ✅ | 63 |
| 9–10 | execution-engine + paper-trading: slicing, retries, transports paper/live | ✅ | 40 + 23 |
| 11 | ai-engine: régimen de mercado, ranking, underperformance | ✅ | 42 |
| 12 | optimizer + scheduler: búsqueda de parámetros, gate out-of-sample, cron | ✅ | 26 + 21 |
| 13 | frontend: dashboard Next.js completo contra el gateway | ✅ | 16 |
| 14 | Monitoreo: `/metrics` en los 14 servicios, Prometheus, Grafana provisionado, promtail→Loki | ✅ | — |
| 15 | Escalabilidad: resources/limits, HPAs, `docs/SCALABILITY.md` | ✅ | — |

Suma: **982 tests backend** (todos en verde) + **16 frontend**.

## Qué falta para producción

- **Credenciales reales de broker**: los conectores apuntan a URLs demo. El
  credential store cifrado (Fernet, `CREDENTIAL_STORE=db`) ya existe pero el
  default sigue siendo `memory`; falta Vault/KMS para las claves.
- **Streaming**: market data por websocket (hoy `stream_market_data` es
  polling) y push de fills al frontend (hoy la UI hace polling).
- **Gate de coherencia con backtest**: implementado pero desactivado, porque
  nada alimenta todavía un baseline de backtest en `build_readiness`. Activarlo
  sin eso bloquearía la promoción a live para siempre en vez de endurecerla.
- **Revocación de access tokens**: `logout` revoca el refresh; el access sigue
  válido hasta expirar (15 min). Falta denylist si eso no basta.
- **`SESSION_COOKIE_SECURE=true`** en producción: por defecto es `false` para
  que la cookie de sesión funcione sobre http en local, pero sin él la cookie
  viaja en claro fuera de localhost.
- **OAuth real**: rellenar `GOOGLE_CLIENT_ID/SECRET` con credenciales reales.
- **k8s productivo**: overlays con secrets reales, ingress/TLS, PodDisruption
  Budgets, y los puntos de estado de SCALABILITY.md (scheduler leader
  election, sesiones de broker compartidas).
