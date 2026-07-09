# Arquitectura General — TradingPlatform

## 1. Objetivo

Plataforma de trading algorítmico modular, multi-broker, multi-mercado, multi-estrategia,
multi-IA y multi-usuario, capaz de escalar de un bot a miles de estrategias sin cambios
estructurales. Ninguna decisión de trading vive en la capa de presentación.

## 2. Principios (no negociables)

1. **Modularidad**: cada servicio tiene una única responsabilidad y expone una interfaz
   (REST/gRPC + eventos), nunca acceso directo a la base de datos de otro servicio.
2. **Independencia de proveedor**: brokers/exchanges se integran vía `BrokerConnector`,
   un contrato común. Cambiar Binance por Kraken no toca ninguna estrategia.
3. **Las estrategias no ejecutan, proponen**: una estrategia emite una `TradeSignal`.
   Solo el `Risk Engine` + `Portfolio Engine` deciden si se convierte en `Order`.
4. **Toda orden pasa por el Risk Engine**. Sin excepciones, sin bypass.
5. **Auditable por diseño**: cada señal, decisión de riesgo, orden, error y cambio de
   configuración se persiste con timestamp, actor y motivo.
6. **Alta disponibilidad**: todo servicio es stateless donde sea posible; el estado vive en
   Postgres/Redis. Un crash de servicio no debe dejar posiciones huérfanas (reconciliación
   al arrancar contra el broker).
7. **Configuración dinámica**: brokers, mercados, estrategias, riesgo y usuarios se
   configuran en base de datos vía la web, nunca recompilando.

## 3. Mapa de servicios (Fase 1)

| Servicio | Responsabilidad | Depende de |
|---|---|---|
| `gateway` | AuthN/AuthZ, rate limiting, enrutamiento API, agregación para el frontend | auth-service |
| `auth-service` | Usuarios, JWT, OAuth, MFA, roles, auditoría | postgres |
| `strategy-engine` | Carga plugins de estrategia, evalúa condiciones, emite `TradeSignal` | market-data, NATS |
| `risk-engine` | Valida cada `TradeSignal` contra límites de riesgo, tamaño de posición, circuit breakers | portfolio-engine |
| `portfolio-engine` | Estado de cuenta: exposición, margen, correlación, PnL, drawdown | postgres, redis |
| `ai-engine` | Régimen de mercado, ranking/selección de estrategias, optimización de parámetros | strategy-engine (lectura) |
| `execution-engine` | Convierte `Order` aprobada en órdenes de broker, reintentos, confirmación | broker-connectors |
| `broker-connectors` | Adaptadores por broker/exchange (IBKR, Binance, MT5...) implementando `BrokerConnector` | — |
| `backtester` | Simula estrategias contra histórico con spread/slippage/comisión/latencia | strategy-engine, market-data |
| `optimizer` | Búsqueda de parámetros + validación out-of-sample antes de promover cambios | backtester |
| `paper-trading` | Mismo `execution-engine`, adapter de broker "simulado" en vez de real | execution-engine |
| `notification-service` | Alertas (email/push/webhook) sobre eventos de riesgo, ejecución, sistema | NATS |
| `scheduler` | Cron de reentrenamiento, reoptimización, jobs periódicos | NATS |
| `trading-engine` | Orquestador del flujo señal → riesgo → portafolio → ejecución (coordinador, sin lógica propia) | todos los anteriores |

Frontend (Next.js) y Mobile (Flutter) consumen exclusivamente el `gateway`. Nunca llaman a
un servicio interno directamente.

## 4. Flujo de una orden (contrato de referencia)

```
MarketData → StrategyEngine.evaluate() → TradeSignal
TradeSignal → RiskEngine.validate(signal, portfolio_state) → RiskDecision(approved|rejected, sized_order)
RiskDecision.approved → PortfolioEngine.reserve(exposure)
sized_order → ExecutionEngine.submit(order) → BrokerConnector.place_order()
BrokerConnector → ExecutionReport (fill/partial/rejected/error)
ExecutionReport → PortfolioEngine.update() + AuditLog.record() + NotificationService (si aplica)
```

Cada flecha es un evento NATS (`signal.created`, `risk.decision`, `order.submitted`,
`execution.report`) además de una llamada síncrona donde se requiere respuesta inmediata
(p. ej. RiskEngine.validate es síncrono; NotificationService es asíncrono).

## 5. Contratos principales (interfaces, Fase 1 = stubs tipados, sin lógica)

### 5.1 `TradeSignal`
```
id, strategy_id, symbol, market, side (buy/sell), confidence, timeframe,
suggested_size, stop_loss, take_profit, generated_at, metadata{}
```

### 5.2 `RiskDecision`
```
signal_id, approved: bool, reason, max_size_allowed, adjusted_stop,
risk_checks_passed: [], risk_checks_failed: [], decided_at
```

### 5.3 `Order`
```
id, signal_id, symbol, side, quantity, order_type, price, status,
broker, account_id, execution_mode (paper|live), created_at
```

### 5.4 `BrokerConnector` (interfaz que cada conector debe implementar)
```
connect(), disconnect(), is_connected()
place_order(order) -> ExecutionReport
cancel_order(order_id)
get_positions() -> [Position]
get_account_state() -> AccountState
stream_market_data(symbols) -> AsyncIterator[Tick]
get_historical_data(symbol, timeframe, start, end) -> [Bar]
```

### 5.5 `Strategy` (interfaz que cada plugin de estrategia implementa)
```
metadata: {id, name, version, category, markets[], timeframes[]}
parameters: {schema}
on_bar(context) -> TradeSignal | None
on_tick(context) -> TradeSignal | None   # opcional, solo estrategias intradía
required_filters() -> []
```

### 5.6 `RiskLimits` (configuración, no código)
```
max_risk_per_trade, max_daily_loss, max_weekly_loss, max_monthly_loss,
max_drawdown, max_floating_drawdown, max_leverage, max_correlation,
max_exposure_per_symbol, max_exposure_per_sector, circuit_breaker_thresholds{}
```

## 6. Modelo de datos inicial (Postgres, resumen — ver `infra/docker/init.sql` para DDL)

- `users`, `roles`, `user_roles`, `audit_log`
- `brokers`, `broker_credentials` (cifradas), `broker_accounts`
- `markets`, `symbols`
- `strategies`, `strategy_versions`, `strategy_configs` (por usuario/cuenta)
- `risk_limits` (por cuenta/usuario)
- `signals`, `risk_decisions`, `orders`, `executions`, `positions`
- `backtest_runs`, `backtest_results`
- `optimization_runs`, `optimization_results`
- `notifications`, `system_events`

## 7. Comunicación entre servicios

- **Síncrono (REST/gRPC)**: gateway ↔ servicios, risk-engine.validate (requiere respuesta
  inmediata antes de ejecutar).
- **Asíncrono (NATS)**: todo lo demás — señales, reportes de ejecución, alertas, eventos de
  auditoría, triggers de reentrenamiento.
- **Cache (Redis)**: estado de portafolio en caliente, rate limiting, sesiones.

## 8. Seguridad

- MFA en `auth-service`; JWT de corta duración + refresh token.
- Credenciales de broker cifradas at-rest (KMS/Vault-ready, stub en Fase 1).
- RBAC: roles `admin`, `trader`, `viewer`, `auditor`.
- Todo endpoint del gateway pasa por middleware de auditoría.

## 9. Estándares de código y pruebas (aplican desde Fase 1)

- Cada servicio Python: `FastAPI` + `pydantic` para contratos, `pytest` para pruebas,
  tipado estricto (`mypy` opcional pero recomendado).
- Cada servicio expone `/health` y `/ready`.
- Ningún servicio contiene lógica de otro servicio; comunicación solo por contrato.
- Pipeline: lint → type-check → unit tests → build imagen Docker → (futuro) despliegue.

## 10. Progresión obligatoria (no saltar fases)

Backtesting → Paper Trading → Real. Un cambio de estrategia o parámetro solo se promueve a
`live` si supera backtesting y paper trading con métricas iguales o mejores fuera de
muestra. El único cambio entre paper y real es `execution_mode`; la lógica es idéntica.

## 11. Qué NO incluye la Fase 1

- Lógica de trading real de ninguna estrategia.
- Conectores de broker reales (solo interfaz + un stub "simulado").
- Modelos de IA entrenados (solo el servicio esqueleto y el contrato).
- Kubernetes de producción (se entrega manifiesto base, no tuning de producción).
