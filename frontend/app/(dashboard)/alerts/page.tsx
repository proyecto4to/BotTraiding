"use client";

/**
 * Alerts: risk events (rejections, circuit-breaker trips, limit updates).
 * Polls GET /api/risk/events/{account} every 15s. The risk-engine persists
 * risk_events rows but does not expose the list endpoint yet, so this page
 * degrades gracefully to an explanatory empty state until it lands.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge, EmptyState, LoadingSkeleton } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useSettings } from "@/lib/settings";
import type { RiskEvent } from "@/lib/types";

const POLL_MS = 15_000;

export default function AlertsPage() {
  const { accountId } = useSettings();
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await api.get<RiskEvent[]>(`/api/risk/events/${accountId}`, {
        silent: true,
        query: { limit: 100 },
      });
      setEvents(Array.isArray(list) ? list : []);
      setUnavailable(false);
    } catch (err) {
      // 404: endpoint not built yet; 502: risk-engine down. Either way the
      // page shows a calm empty state and keeps polling.
      setUnavailable(err instanceof ApiError);
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    setLoading(true);
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <>
      <div className="page-head">
        <h1>Alerts — {accountId}</h1>
        <span className="muted">refreshes every 15s</span>
      </div>

      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : events.length === 0 ? (
        <EmptyState
          title="No alerts"
          hint={
            unavailable
              ? "The risk-events feed is not available yet (endpoint under construction or risk-engine down). This page will populate automatically once it responds."
              : "Risk rejections, circuit-breaker trips and limit changes will appear here."
          }
        />
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Type</th>
                <th>Signal</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{fmtDateTime(event.created_at)}</td>
                  <td>
                    <Badge tone={eventTone(event.event_type)}>{event.event_type}</Badge>
                  </td>
                  <td>{event.signal_id ?? "—"}</td>
                  <td
                    style={{
                      whiteSpace: "normal",
                      maxWidth: 480,
                      fontFamily: "var(--mono)",
                      fontSize: "0.72rem",
                    }}
                  >
                    {summarizePayload(event.payload)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function eventTone(eventType: string): "green" | "red" | "amber" | "neutral" {
  const t = eventType.toLowerCase();
  if (t.includes("circuit_breaker") || t.includes("halt")) return "red";
  if (t.includes("rejected") || t.includes("rejection")) return "amber";
  if (t.includes("reset") || t.includes("limits_updated")) return "neutral";
  return "neutral";
}

function summarizePayload(payload: Record<string, unknown>): string {
  try {
    const text = JSON.stringify(payload);
    return text.length > 300 ? `${text.slice(0, 300)}…` : text;
  } catch {
    return String(payload);
  }
}
