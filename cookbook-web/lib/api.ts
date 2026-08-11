import type {
  AutoResponse,
  Catalogue,
  Fit,
  ManualFit,
  Probe,
  Selection,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_COOKBOOK_API_URL ?? "http://127.0.0.1:8001";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function getProbe(fresh = false): Promise<Probe> {
  return request(`/api/probe${fresh ? "?fresh=1" : ""}`);
}

export function getCatalogue(): Promise<Catalogue> {
  return request("/api/catalogue");
}

export interface AutoFitParams {
  roles: string[];
  require_cloning: boolean;
  whole_bible_bonus: number;
  basis: string;
}

export function postAutoFit(params: AutoFitParams): Promise<AutoResponse> {
  return request("/api/fit/auto", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export interface ManualFitParams {
  selection: Selection;
  basis: string;
  whole_bible_bonus: number;
}

export function postManualFit(params: ManualFitParams): Promise<ManualFit> {
  return request("/api/fit/manual", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function getConfig(): Promise<Record<string, unknown> | null> {
  return request("/api/config");
}

export interface ConfigWriteParams {
  selection: Selection;
  basis: string;
  whole_bible_bonus: number;
  agent: boolean;
}

export function postConfig(params: ConfigWriteParams): Promise<
  Record<string, unknown>
> {
  return request("/api/config", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function getInstalled(): Promise<string[]> {
  return request("/api/installed");
}
