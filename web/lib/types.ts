export type Role = "llm" | "embedding" | "tts";
export type Device = "gpu" | "cpu";
export type Strategy = "whole-bible" | "retrieval";
export type Basis = "whole-machine" | "free-now";
export type Figures = "estimated" | "hub" | "measured";
export type ToolCalling = "native" | "prompted" | "none";

export interface Probe {
  in_container: boolean;
  ram_total_bytes: number;
  ram_available_bytes: number;
  ram_ceiling_bytes: number;
  ram_ceiling_source: string;
  cpu_count: number;
  disk_free_bytes: number;
  gpu: {
    present: boolean;
    name: string;
    total_bytes: number;
    free_bytes: number;
    used_bytes: number;
    driver: string;
    vendor: string;
    diagnosis: string;
  };
  internet: boolean;
  installed_repos: string[];
  warnings: string[];
}

export interface KVGeometry {
  layers: number;
  kv_heads: number;
  head_dim: number;
  bytes_per_elem: number;
}

export interface ModelEntry {
  id: string;
  role: Role;
  repo: string;
  weights_bytes: number;
  runtime_overhead_bytes: number;
  devices: Device[];
  quality: number;
  quant: string | null;
  max_context: number | null;
  kv: KVGeometry | null;
  cloning: boolean | null;
  tool_calling: ToolCalling;
  figures: Figures;
  notes: string;
}

export interface Provider {
  id: string;
  label: string;
  adapter: "openai" | "anthropic";
  api_key_env: string;
  base_url: string | null;
  default_model: string;
  context_tokens: number;
  free_tier: string;
  tool_calling: boolean;
  notes: string;
}

export interface Catalogue {
  bible_tokens: number;
  models: ModelEntry[];
  providers: Provider[];
}

export interface PlacementInfo {
  model: string | null;
  device: Device | null;
  provider: string | null;
}

export interface Fit {
  ok: boolean;
  score: number;
  strategy: Strategy;
  context_tokens: number;
  placements: Partial<Record<Role, PlacementInfo>>;
  vram_used: number;
  ram_used: number;
  vram_over: number;
  ram_over: number;
  per_model: Partial<Record<Role, number>>;
  reasons: string[];
  verdict: string;
}

export interface ManualFit extends Fit {
  bible_tokens: number;
}

export interface AutoResponse {
  fits: Fit[];
  shortfall: string | null;
}

export interface Selection {
  context_tokens: number;
  placements: Partial<Record<Role, { model: string; device: Device }>>;
  llm_provider?: string | null;
  tts_provider?: string | null;
  tts_voice_gender?: "male" | "female" | null;
  embedding_provider?: string | null;
}

export interface DownloadModelStatus {
  id: string;
  role: Role;
  total_bytes: number;
  downloaded_bytes: number;
  done: boolean;
  error: string | null;
}

export interface DownloadStatus {
  models: DownloadModelStatus[];
  active: boolean;
}

export const CONTEXT_CANDIDATES = [4096, 8192, 16384, 32768, 65536] as const;
export const ROLES: Role[] = ["llm", "embedding", "tts"];
