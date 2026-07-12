# Plan hacia la autonomía total — modo prompt

> Complementa a [`PLAN-AUTONOMIA.md`](PLAN-AUTONOMIA.md) (la visión conceptual
> por fases). Este documento es la **ejecución en forma de prompts**: cada
> prompt (P0, P1, …) es autónomo y se le entrega a un agente/Codex de a uno, en
> orden, anclado al estado real del código.

> **Objetivo final:** que el sistema aprenda y opere solo. El usuario únicamente
> pulsa un interruptor **ON/OFF**. En ON: detecta el régimen del mercado, elige
> y pondera estrategias, optimiza parámetros de forma continua, crea/ajusta/pausa
> bots, ejecuta bajo control de riesgo, y apaga lo que rinde mal — sin
> intervención. En OFF: pausa ordenadamente. La regla de oro se mantiene:
> **backtest → paper → real**, y el modo real exige activación explícita admin.

---

## Parte A — Análisis del estado actual (2026-07)

**Probado y funcionando (~880 tests):** las 16 Fases (0-15), la biblioteca de 16
estrategias, el Risk Engine completo, el orquestador de bots (trading-engine) con
su suite E2E, el conector Binance real (REST firmado + websocket + testnet),
notificaciones (email/Telegram/webhook) y el dashboard web + móvil.

**A medias (commiteado sin verificar):**
- Idempotencia de órdenes (`client_order_id` en execution-engine + guarda de
  ingesta idempotente en portfolio-engine): **código presente, sin tests** (las
  suites siguen en 40 y 22, sin cobertura nueva).
- Reconciliación (`portfolio-engine/app/reconcile.py`): **completa, pero sin
  tests, sin endpoint cableado en `main.py`, sin hook de arranque**.
- Cifrado de credenciales de broker: **no empezado** (sigue el
  `InMemoryCredentialStore`: se pierde al reiniciar y no cifra).

**La brecha hacia la autonomía:** las piezas inteligentes existen (AI Engine,
Optimizer, Scheduler) pero **nadie las coordina automáticamente**. El AI
recomienda pero no actúa; el optimizer optimiza solo si alguien lo dispara; el
master switch del dashboard (`/api/automation/toggle`) es un stub en memoria que
no controla nada. El salto a autonomía = construir el **cerebro que ata todo
detrás del interruptor**.

Brechas concretas: (1) sin datos de mercado continuos compartidos entre bots;
(2) sin controlador de autonomía que orqueste AI→selección→bots→riesgo; (3) el
AI solo recomienda; (4) el lazo reoptimizar→validar→promover→realimentar no está
cerrado de punta a punta; (5) sin asignación automática de capital; (6) sin
auto-halt global ni kill switch real; (7) estado en memoria (rate limiter,
sesiones) impide réplicas y reinicios sin pérdida.

---

## Parte B — La visión del interruptor

El **Autonomy Controller** es una máquina de estados detrás del master switch:

```
        OFF ──(ON)──► LEARNING ──(datos+validación OK)──► TRADING_PAPER
         ▲               │                                     │
         │               │                          (gates paper→live + admin)
         └──(OFF)──────── ┴──────────────◄── HALTED ◄──(auto-halt riesgo)──┐
                                                                            │
                                          TRADING_LIVE ─(drawdown/kill)─────┘
```

- **OFF**: nada opera. Bots pausados.
- **LEARNING**: recopila datos, corre backtests/optimización, el AI clasifica
  régimen y prepara la selección. No manda órdenes.
- **TRADING_PAPER**: opera en paper con la selección del AI, aprendiendo en
  vivo. Estado por defecto de "encendido".
- **TRADING_LIVE**: solo tras superar los gates (P18) y con admin.
- **HALTED**: el auto-halt de riesgo o el kill switch lo fuerzan; requiere reset
  manual (admin).

Cada transición y decisión automática queda **auditada** y notificada.

---

## Parte C — El plan en prompts

Preámbulo común a **todos** los prompts (pegar al inicio de cada uno):

> Repo: `c:/Users/Dell Vostro/OneDrive/Documentos/GitHub/BotTraiding` (Windows,
> rutas con espacios entre comillas). Leé `docs/ARCHITECTURE.md` primero (fuente
> de verdad: contratos, flujo de orden, "toda orden pasa por el Risk Engine").
> Contratos compartidos en `services/shared/contracts` (`trading_contracts`,
> solo lectura). Cada servicio corre en Postgres (Docker, Alembic con su propio
> `version_table`) y en SQLite local (`Base.metadata.create_all`) — mantené los
> modelos agnósticos del dialecto y agregá revisiones Alembic nuevas, no edites
> las existentes. Verificá con pytest en el `.venv` del servicio hasta que quede
> verde; reportá conteos reales, nunca declares éxito con tests en rojo. No crees
> commits. Alcance estricto a los servicios indicados; si necesitás env vars
> nuevas, reportalas en vez de tocar `docker-compose.yml`.

### Bloque 0 — Cerrar fundaciones (confianza antes de automatizar)

**P0 — Terminar y testear idempotencia + reconciliación**
Alcance: `services/execution-engine`, `services/portfolio-engine`.
El código ya existe pero sin pruebas. (1) Cablear
`POST /portfolio/{account_id}/reconcile` (admin JWT; `apply=false` por defecto →
solo reporta; `apply=true` → ajusta y registra ejecuciones sintéticas
`source="reconciliation"`) usando `reconcile.py`; añadir el hook de arranque
report-only (`RECONCILE_ON_START`). (2) En execution-engine marcar ejecuciones
"stale" (submitted/partial más viejas que `EXECUTION_STALE_AFTER_SECONDS`) como
`unknown` y exponerlas en `GET /executions?status=unknown`. (3) Tests: reintento
tras timeout reusa `client_order_id` y no duplica; ingesta doble del mismo
ExecutionReport es no-op; math de reconciliación por clase de discrepancia +
tolerancia; `apply=true` corrige estado y crea ejecuciones sintéticas,
`apply=false` no muta nada; marcado stale al arrancar. Correr también
`tests/integration` (camino dorado sigue verde con idempotencia).

**P1 — Credenciales de broker cifradas y persistentes**
Alcance: `services/broker-connectors`.
`EncryptedDbCredentialStore` (cumple el ABC `CredentialStore` existente) con
Fernet (`cryptography`), clave desde `BROKER_CRED_KEY` (se niega a arrancar sin
ella cuando `CREDENTIAL_STORE=db`), tabla `broker_credentials` (modelo agnóstico
+ `db.py` + `models.py` + Alembic `version_table="alembic_version_broker"` +
entrypoint `upgrade head`; también `create_all` para SQLite local). Selección por
env `CREDENTIAL_STORE=memory|db` (default `memory`). Endpoint admin
`POST /connectors/credentials/rotate` que re-cifra con clave nueva. Tests:
round-trip, negativa sin clave, rotación (la clave vieja ya no descifra),
secretos ausentes de respuestas y `repr`.

### Bloque 1 — Datos e infraestructura para operar sin supervisión

**P2 — Servicio de market-data con caché compartida**
Alcance: nuevo `services/market-data` (o módulo en broker-connectors; documentar
la decisión). Una sola suscripción por símbolo/timeframe alimentada por el
websocket de Binance, cacheada en Redis, servida a todos los bots vía
`GET /market-data/{symbol}?timeframe=&limit=` + stream interno. Evita que N bots
agoten el rate limit pidiendo velas por separado. Seam `MarketDataSource`
inyectable; fallback a REST klines si el ws cae. Tests con ws y Redis simulados.

**P3 — Estado compartido en Redis (habilita réplicas y reinicios)**
Alcance: `gateway` (rate limiter), `broker-connectors` (sesiones), `trading-engine`
(locks de bot). Reemplazar los stores en memoria por implementaciones Redis
detrás de las interfaces existentes (cambio de una clase, no de la lógica). Sin
Redis → degradar a memoria con warning. Tests con Redis simulado; dos "réplicas"
comparten el límite.

### Bloque 2 — El cerebro autónomo (núcleo de "aprende y opera solo")

**P4 — Autonomy Controller (máquina de estados detrás del switch)**
Alcance: nuevo `services/autonomy-controller` (p.ej. puerto 8014) o módulo en
trading-engine (recomendado servicio propio por responsabilidad única). Implementa
la máquina de estados de la Parte B. Cada "tick" (cadencia por env, disparado por
el scheduler): pide al AI el régimen (`POST /ai/regime`) y la selección ponderada
(`POST /ai/select`) con el rendimiento reciente de portfolio-engine; traduce la
selección en acciones sobre trading-engine (crear/ajustar/pausar bots) respetando
el presupuesto de riesgo. Persiste cada decisión (`autonomy_decisions`: estado,
régimen, selección, acciones, motivo) — Alembic `version_table="alembic_version_autonomy"`.
Endpoints: `GET /autonomy/state`, `POST /autonomy/enable|disable` (admin),
`GET /autonomy/decisions?limit=`. Eventos `autonomy.*` (seam NATS + fallback log).
Clientes downstream inyectables y mockeados. Tests: transiciones, traducción
selección→acciones, respeto del presupuesto de riesgo, degradación si un
downstream cae.

**P5 — Governor de ciclo de vida de estrategias**
Alcance: `services/autonomy-controller` (consume recomendaciones de ai-engine).
Actúa automáticamente sobre las recomendaciones del AI (apagar underperformers
vía `PATCH /strategies/{key}`, encender las favorecidas por el régimen) **dentro
de guardarraíles auditables**: nunca apaga sin recomendación validada; tope de
cambios por ventana; toda acción persistida y notificada. Modo `shadow` (solo
loguea) vs `active` (aplica), default shadow. Tests: recomendación dispara acción
en active y solo log en shadow; tope respetado.

**P6 — Cerrar el lazo de aprendizaje continuo**
Alcance: `scheduler`, `optimizer`, `autonomy-controller`. Job periódico: por cada
estrategia habilitada → reoptimizar (walk-forward OOS, promoción gated) → si
promueve, aplicar params a strategy-engine → el Autonomy Controller recoge la
nueva config en su próximo tick. Cadencia por env. Tests: el job encadena
reoptimización→promoción→feedback con downstreams mockeados; una mejora que no
supera OOS no se promueve.

**P7 — Asignación automática de capital**
Alcance: `services/autonomy-controller` (lee risk-engine y portfolio-engine).
Reparte capital entre bots/estrategias según los pesos del AI y el presupuesto de
riesgo. Produce un `AllocationPlan` que fija el tamaño base de cada bot; el Risk
Engine mantiene la última palabra por operación. Tests: suma ≤ presupuesto;
rebalanceo cuando cambian los pesos; respeto de límites de exposición.

### Bloque 3 — El interruptor y su seguridad

**P8 — Master switch real (reemplazar el stub del gateway)**
Alcance: `services/gateway` (proxy hacia autonomy-controller; quitar el
`AutomationState` en memoria). `/api/automation/*` proxya a `autonomy-controller`
(`/autonomy/*`), con RBAC (solo admin activa), auditoría y **kill switch**
(`POST /autonomy/kill`) que fuerza HALTED y, opcional, dispara cierre de
posiciones vía execution-engine. Tests de proxy + gate de rol.

**P9 — Auto-halt global por riesgo**
Alcance: `autonomy-controller` (lee risk/portfolio). Si el drawdown agregado o la
pérdida del período superan umbrales (`AUTONOMY_MAX_DRAWDOWN`,
`AUTONOMY_MAX_DAILY_LOSS`), la automatización pasa sola a HALTED, notifica crítico
y requiere reset admin. Circuit breaker a nivel plataforma, por encima de los de
cada cuenta. Tests: cruce de umbral → HALTED + evento; por debajo → sigue.

**P10 — Panel de autonomía en el dashboard**
Alcance: `frontend/` (+ `mobile/` opcional). Página "Autonomy": botón ON/OFF,
estado actual, régimen detectado, estrategias activas con pesos, bots vivos,
decisiones automáticas recientes (con motivo), PnL y drawdown agregados, estado
del auto-halt. Todo vía gateway; degradar con elegancia si el controller no
responde. Tests de render con fetch mockeado.

### Bloque 4 — Robustez y calidad (mejoras transversales)

- **P11 — Unificar el esquema de DB:** Alembic única verdad; retirar/alinear
  `init.sql` para eliminar la colisión de tablas.
- **P12 — Streaming en tiempo real al dashboard:** WebSocket/SSE en el gateway
  (posiciones, PnL, decisiones, alertas en vivo; hoy es polling).
- **P13 — Backtests/optimizaciones como jobs async:** cola (Redis/NATS) para que
  un trabajo largo no bloquee; endpoints devuelven job id + estado.
- **P14 — Métricas de negocio en Prometheus + Grafana:** señales/rechazos/fills/
  PnL/drawdown/decisiones de autonomía; panel "Autonomy & Trading".
- **P15 — Endurecimiento de seguridad:** tokens en cookie httpOnly (BFF),
  secretos en Vault/KMS, brute-force en `/auth/login`.
- **P16 — Promover el patrón Binance a los otros 7 conectores:** firma real,
  endpoints reales y websocket por broker, uno a uno con su suite.
- **P17 — Ampliar la biblioteca de estrategias** hacia el objetivo 1000+, por
  categoría, cada una con backtest de referencia.

### Bloque 5 — Camino a real (gate final)

**P18 — Gates automáticos paper→live**
El Autonomy Controller solo permite `TRADING_LIVE` si se cumplen gates
verificables: N semanas de paper, métricas mínimas (Sharpe/drawdown), coherencia
paper-vs-backtest dentro de tolerancia. Configurable, auditado, y siempre con
confirmación admin. Tests de cada gate (pasa/rechaza).

---

## Parte D — Orden y prioridades

| Orden | Prompt | Por qué |
|---|---|---|
| 1 | **P0** idempotencia+reconciliación (terminar+test) | Crítico pre-live; ya casi hecho |
| 2 | **P1** credenciales cifradas | Crítico pre-live |
| 3 | **P2** market-data compartida | La autonomía necesita datos continuos |
| 4 | **P3** estado en Redis | Réplicas/reinicios sin pérdida |
| 5 | **P4** Autonomy Controller | Núcleo del "opera solo" |
| 6 | **P5** governor de estrategias | El AI por fin actúa |
| 7 | **P6** lazo de aprendizaje | El "aprende solo" |
| 8 | **P7** asignación de capital | Reparto automático |
| 9 | **P8** master switch real | El interruptor |
| 10 | **P9** auto-halt global | Seguridad de la autonomía |
| 11 | **P10** panel de autonomía | Ver qué hace y por qué |
| 12+ | **P11–P17** | Robustez/calidad transversal |
| Final | **P18** gates paper→live | Único camino a dinero real |

**La autonomía "de verdad" queda operativa al terminar el Bloque 2 + P8.** El
resto la endurece y la lleva con seguridad hacia real.

## Cómo ejecutar

1. Prompts **en orden**; no saltar bloques (hay dependencias).
2. Uno por vez a un agente/Codex, con el preámbulo común al inicio.
3. Tras cada prompt: revisar reporte, confirmar tests verdes, commitear.
4. El Bloque 0 es obligatorio antes de confiar en cualquier operación.
