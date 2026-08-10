"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelStatus } from "@/lib/api";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export default function Page() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e) => setError(String(e)));
    getModelStatus()
      .then(setStatus)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <pre>Backend unreachable: {error}</pre>;

  return (
    <main style={{ padding: 24 }}>
      <h1>Admin</h1>
      <p>health: {health ? JSON.stringify(health) : "loading..."}</p>
      <p>model: {status ? JSON.stringify(status) : "loading..."}</p>
    </main>
  );
}
