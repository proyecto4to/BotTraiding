/**
 * System health probing — all via the gateway.
 *
 * Upstream /health endpoints live at each service root and are not directly
 * proxied, so we probe one cheap real endpoint per segment and classify:
 * - network error on the gateway's own /health  -> gateway down
 * - 502 ("Upstream 'x' unavailable")            -> that service is down
 * - any other HTTP response (200/401/404/...)    -> the service answered -> up
 */

import { GATEWAY_URL } from "@/lib/api";
import { getAccessToken } from "@/lib/token-store";
import type { HealthTile } from "@/lib/types";

interface Probe {
  service: string;
  path: string;
}

function probes(accountId: string): Probe[] {
  return [
    { service: "gateway", path: "/health" },
    { service: "auth-service", path: "/api/auth/me" },
    { service: "strategy-engine", path: "/api/strategies" },
    { service: "risk-engine", path: `/api/risk/circuit-breaker/${accountId}` },
    { service: "portfolio-engine", path: `/api/portfolio/${accountId}` },
    { service: "broker-connectors", path: "/api/brokers/connectors" },
    { service: "execution-engine", path: "/api/executions/modes" },
    { service: "backtester", path: "/api/backtests/health" },
    { service: "ai-engine", path: "/api/ai/health" },
  ];
}

async function probeOne(probe: Probe): Promise<HealthTile> {
  try {
    const token = getAccessToken();
    const response = await fetch(new URL(probe.path, GATEWAY_URL).toString(), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (response.status === 502) return { service: probe.service, status: "down" };
    return { service: probe.service, status: "up" };
  } catch {
    return { service: probe.service, status: "down" };
  }
}

export async function probeSystemHealth(accountId: string): Promise<HealthTile[]> {
  const results = await Promise.allSettled(probes(accountId).map(probeOne));
  return results.map((result, i) =>
    result.status === "fulfilled"
      ? result.value
      : { service: probes(accountId)[i].service, status: "unknown" },
  );
}
