"use client";

/**
 * Brokers: available connectors, connection status per broker/account and a
 * connect form. API key/secret are POSTed straight to the gateway and NEVER
 * persisted client-side — the form is cleared after submit and the values
 * exist only in transient component state.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useToast } from "@/components/Toast";
import { Badge, EmptyState, ErrorBanner, LoadingSkeleton, SectionTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useSettings } from "@/lib/settings";
import type { ConnectResponse, ConnectorListResponse, ConnectorStatusResponse } from "@/lib/types";

export default function BrokersPage() {
  const { accountId } = useSettings();
  const { push } = useToast();

  const [brokers, setBrokers] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<Record<string, ConnectorStatusResponse>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Connect form — transient only, never stored.
  const [broker, setBroker] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [demo, setDemo] = useState(true);
  const [connecting, setConnecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.get<ConnectorListResponse>("/api/brokers/connectors", {
        silent: true,
      });
      setBrokers(list.brokers);
      setError(null);
      const results = await Promise.allSettled(
        list.brokers.map((b) =>
          api.get<ConnectorStatusResponse>(`/api/brokers/connectors/${b}/status`, {
            silent: true,
            query: { account_id: accountId },
          }),
        ),
      );
      const next: Record<string, ConnectorStatusResponse> = {};
      results.forEach((result, i) => {
        if (result.status === "fulfilled") next[list.brokers[i]] = result.value;
      });
      setStatuses(next);
    } catch {
      setError("broker-connectors is not responding.");
      setBrokers([]);
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  const connect = async (e: FormEvent) => {
    e.preventDefault();
    if (!broker) return;
    setConnecting(true);
    try {
      const response = await api.post<ConnectResponse>(
        `/api/brokers/connectors/${broker}/connect`,
        { api_key: apiKey, api_secret: apiSecret, demo, account_id: accountId },
      );
      push(
        `${response.broker} ${response.connected ? "connected" : "not connected"} (${
          response.demo ? "demo" : "REAL"
        }).`,
        response.connected ? "success" : "error",
      );
      await load();
    } catch {
      /* toasted */
    } finally {
      // Credentials never linger in the DOM/state after submit.
      setApiKey("");
      setApiSecret("");
      setConnecting(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Brokers — account {accountId}</h1>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {loading ? (
        <LoadingSkeleton rows={4} />
      ) : (
        <div className="grid-2">
          <div className="card">
            <SectionTitle>Connectors</SectionTitle>
            {brokers.length === 0 ? (
              <EmptyState title="No broker connectors registered" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Broker</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {brokers.map((b) => {
                      const status = statuses[b];
                      return (
                        <tr key={b}>
                          <td>{b}</td>
                          <td>
                            {status?.connected ? (
                              <Badge tone="green">connected</Badge>
                            ) : (
                              <Badge tone="neutral">disconnected</Badge>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <SectionTitle>Connect</SectionTitle>
            <form onSubmit={connect} autoComplete="off">
              <div className="form-row">
                <label className="label" htmlFor="broker-select">
                  Broker
                </label>
                <select
                  id="broker-select"
                  className="input"
                  value={broker}
                  onChange={(e) => setBroker(e.target.value)}
                  required
                >
                  <option value="">Select…</option>
                  {brokers.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="label" htmlFor="broker-key">
                  API key
                </label>
                <input
                  id="broker-key"
                  className="input"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>
              <div className="form-row">
                <label className="label" htmlFor="broker-secret">
                  API secret
                </label>
                <input
                  id="broker-secret"
                  className="input"
                  type="password"
                  autoComplete="off"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                />
                <p className="field-hint">
                  Sent once to the gateway; never stored in the browser.
                </p>
              </div>
              <div className="form-row">
                <label className="label" htmlFor="broker-demo">
                  Demo account
                </label>
                <input
                  id="broker-demo"
                  type="checkbox"
                  className="toggle"
                  checked={demo}
                  onChange={(e) => setDemo(e.target.checked)}
                />
                {!demo ? (
                  <p className="field-hint" style={{ color: "var(--red)" }}>
                    REAL account selected — live credentials.
                  </p>
                ) : null}
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={connecting || !broker}
              >
                {connecting ? "Connecting…" : "Connect"}
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
