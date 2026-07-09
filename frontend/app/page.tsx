"use client";

import { useEffect, useState } from "react";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

type HealthResponse = {
  status: string;
  service: string;
};

export default function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${GATEWAY_URL}/health`)
      .then((res) => res.json())
      .then((data: HealthResponse) => setHealth(data))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main>
      <h1>TradingPlatform Dashboard</h1>
      <p>Fase 1 skeleton - the frontend talks only to the gateway service.</p>
      <section>
        <h2>Gateway status</h2>
        {health && <p>{health.service}: {health.status}</p>}
        {error && <p>Error reaching gateway: {error}</p>}
        {!health && !error && <p>Loading...</p>}
      </section>
    </main>
  );
}
