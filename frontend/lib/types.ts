/**
 * Typed DTOs mirroring the gateway API surface (see services/gateway).
 * The frontend is presentation-only: display + configuration, never trading
 * logic (docs/ARCHITECTURE.md, principle 1).
 */

// ---- auth-service (/api/auth/*) --------------------------------------------

export interface LoginResponse {
  access_token: string | null;
  refresh_token: string | null;
  token_type: string;
  mfa_required: boolean;
  mfa_pending_token: string | null;
}

export interface UserOut {
  id: string;
  email: string;
  is_active: boolean;
  mfa_enabled: boolean;
  roles: string[];
}

// ---- strategy-engine (/api/strategies/*) -----------------------------------

export interface ParameterSpec {
  name: string;
  type: string; // "int" | "float" | "bool" | "str" | ...
  default: unknown;
  min?: number | null;
  max?: number | null;
  choices?: unknown[] | null;
  description?: string;
}

export interface StrategySummary {
  key: string;
  name: string;
  version: string;
  category: string;
  markets: string[];
  timeframes: string[];
  enabled: boolean;
  description: string;
}

export interface StrategyDetail extends StrategySummary {
  parameters: ParameterSpec[];
  recommended_risk_per_trade: number;
  historical_metrics: Record<string, number>;
  db_id?: string | null;
}

export interface StrategyConfigResponse {
  strategy_key: string;
  version: string;
  user_id: string;
  account_id: string | null;
  overrides: Record<string, unknown>;
  is_active: boolean;
  updated_at: string | null;
}

// ---- risk-engine (/api/risk/*) ---------------------------------------------

export interface ExtendedRiskLimits {
  max_risk_per_trade: number;
  max_daily_loss: number;
  max_weekly_loss: number;
  max_monthly_loss: number;
  max_drawdown: number;
  max_floating_drawdown: number;
  max_leverage: number;
  max_correlation: number;
  max_exposure_per_symbol: number;
  max_exposure_per_sector: number;
  circuit_breaker_thresholds: Record<string, number>;
  max_total_exposure: number;
  min_volume: number;
  max_slippage: number | null;
  max_volatility: number | null;
}

export interface RiskLimitsResponse {
  account_id: string;
  limits: ExtendedRiskLimits;
  is_default: boolean;
}

export interface CircuitBreakerStatus {
  account_id: string;
  state: string; // NORMAL | ... | HARD_HALT
  reason: string | null;
  error_count: number;
  updated_at: string | null;
}

/** Shape of risk_events rows (services/risk-engine/app/models.py). The list
 * endpoint does not exist yet in risk-engine; /alerts polls it and degrades
 * to an empty state until the backend lands. */
export interface RiskEvent {
  id: string;
  account_id: string;
  event_type: string;
  signal_id: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

// ---- portfolio-engine (/api/portfolio/*) -----------------------------------

export interface AccountState {
  account_id: string;
  balance: number;
  equity: number;
  margin_used: number;
  free_margin: number;
  currency: string;
}

export interface Position {
  symbol: string;
  quantity: number;
  average_price: number;
  unrealized_pnl: number;
  account_id: string;
}

export interface ExposureReport {
  account_id: string;
  gross_exposure: number;
  net_exposure: number;
  leverage: number;
  per_symbol: Record<string, number>;
  per_sector: Record<string, number>;
  per_currency: Record<string, number>;
  correlation_matrix: Record<string, Record<string, number>>;
}

export interface DrawdownReport {
  account_id: string;
  equity: number;
  peak_equity: number;
  current_drawdown: number;
  floating_drawdown: number;
}

export interface PortfolioState {
  account: AccountState;
  positions: Position[];
  marks: Record<string, number>;
  exposure: ExposureReport;
  drawdown: DrawdownReport;
  realized_pnl: number;
  unrealized_pnl: number;
  pnl_daily: number;
  pnl_weekly: number;
  pnl_monthly: number;
  updated_at: string;
}

// ---- gateway market config (/config/*) -------------------------------------

export interface MarketOut {
  id: string;
  name: string;
  code: string;
  asset_class: string;
  enabled: boolean;
  trading_hours: Record<string, unknown>;
}

export interface UserMarketOut {
  market_id: string;
  name: string;
  code: string;
  asset_class: string;
  market_enabled: boolean;
  user_enabled: boolean;
  effective_enabled: boolean;
}

// ---- broker-connectors (/api/brokers/*) ------------------------------------

export interface ConnectorListResponse {
  brokers: string[];
}

export interface ConnectResponse {
  broker: string;
  account_id: string;
  connected: boolean;
  demo: boolean;
}

export interface ConnectorStatusResponse {
  broker: string;
  account_id: string;
  connected: boolean;
}

// ---- execution-engine (/api/executions/*) ----------------------------------

export interface ChildOrderOut {
  id: string;
  sequence: number;
  quantity: number;
  status: string;
  filled_quantity: number;
  average_fill_price: number | null;
  attempts: number;
  last_error: string | null;
}

export interface ExecutionOut {
  id: string;
  order_id: string;
  signal_id: string;
  account_id: string;
  symbol: string;
  side: string;
  quantity: number;
  order_type: string;
  price: number | null;
  broker: string;
  execution_mode: string; // "paper" | "live"
  status: string;
  filled_quantity: number;
  average_fill_price: number | null;
  requested_by: string | null;
  created_at: string;
  child_orders: ChildOrderOut[];
}

export interface ModeInfo {
  available: boolean;
  transport: string;
  url: string;
}

export interface ModesResponse {
  default_mode: string;
  override_requires_admin: boolean;
  max_child_size: number;
  modes: Record<string, ModeInfo>;
}

// ---- backtester (/api/backtests/*) -----------------------------------------
// The backtester REST layer is still being built; these mirror
// services/backtester/app/metrics.py summarize() keys and degrade gracefully.

export interface BacktestMetrics {
  cagr?: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  calmar?: number | null;
  max_drawdown?: number | null;
  profit_factor?: number | null;
  expectancy?: number | null;
  win_rate?: number | null;
  [key: string]: number | null | undefined;
}

export interface EquityPoint {
  timestamp: string | number;
  equity: number;
}

export interface BacktestRunRequest {
  strategy_key: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  initial_balance: number;
  params: Record<string, unknown>;
  frictions: {
    spread: number;
    slippage_pct: number;
    commission_pct: number;
    latency_bars: number;
  };
}

export interface BacktestResult {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[] | number[];
  trades?: unknown[];
  [key: string]: unknown;
}

// ---- health ------------------------------------------------------------------

export type ServiceHealth = "up" | "down" | "unknown";

export interface HealthTile {
  service: string;
  status: ServiceHealth;
}
