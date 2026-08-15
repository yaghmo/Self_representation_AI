import type {
  ChatResponse,
  HealthStatus,
  Message,
  ModelStatus,
  Proposal,
  SnapshotEntry,
  StoryRouteResponse,
  ToolResponse,
  VoicePhrases,
  VoiceStatus,
} from "./types";
import { messageToApi } from "./types";

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000";

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
  const response = await fetch(`${SERVICE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthStatus> {
  return request("/health");
}

export function getModelStatus(): Promise<ModelStatus> {
  return request("/model");
}

export function loadModel(port = 8080): Promise<ModelStatus & { status: string }> {
  return request("/model/load", { method: "POST", body: JSON.stringify({ port }) });
}

export function unloadModel(): Promise<{ status: string; model?: string }> {
  return request("/model/unload", { method: "POST" });
}

export interface ChatParams {
  messages: Message[];
  temperature: number;
  maxTokens: number;
  thinking: boolean;
  tools?: Record<string, unknown>[];
  summary?: string;
}

export function postChat(params: ChatParams): Promise<ChatResponse> {
  return request("/chat", {
    method: "POST",
    body: JSON.stringify({
      messages: params.messages.map(messageToApi),
      temperature: params.temperature,
      max_tokens: params.maxTokens,
      thinking: params.thinking,
      tools: params.tools ?? null,
      summary: params.summary ?? "",
    }),
  });
}

export function postAdminTool(name: string, args: Record<string, unknown>): Promise<ToolResponse> {
  return request("/admin/tool", {
    method: "POST",
    body: JSON.stringify({ name, arguments: args }),
  });
}

export function postProposalApply(proposal: Proposal): Promise<{ path: string }> {
  return request("/admin/proposal/apply", {
    method: "POST",
    body: JSON.stringify(proposal),
  });
}

export function getSnapshots(): Promise<{ snapshots: SnapshotEntry[] }> {
  return request("/admin/snapshots");
}

export function postSnapshotRestore(name: string): Promise<{ restored: string }> {
  return request("/admin/snapshots/restore", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function postConvertFile(file: File): Promise<{ text: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${SERVICE_URL}/admin/story/convert-file`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as { text: string };
}

export function postStoryRoute(text: string): Promise<StoryRouteResponse> {
  return request("/admin/story/route", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export interface StoryProposeParams {
  branch: "new" | "append" | "amend";
  storyId?: string;
  eventId?: string;
  text?: string;
  merge?: boolean;
  summary?: string;
  logged?: string;
  keywords?: string[];
  events: { title: string; text: string }[];
}

export function postStoryPropose(params: StoryProposeParams): Promise<ToolResponse> {
  return request("/admin/story/propose", {
    method: "POST",
    body: JSON.stringify({
      branch: params.branch,
      story_id: params.storyId ?? "",
      event_id: params.eventId ?? "",
      text: params.text ?? "",
      merge: params.merge ?? false,
      summary: params.summary ?? "",
      logged: params.logged ?? "",
      keywords: params.keywords ?? [],
      events: params.events,
    }),
  });
}

export interface IngestParams {
  text: string;
  existing?: string;
  merge?: boolean;
}

export function postIngest(params: IngestParams): Promise<{ content: string }> {
  return request("/ingest", {
    method: "POST",
    body: JSON.stringify({
      text: params.text,
      existing: params.existing ?? "",
      merge: params.merge ?? false,
    }),
  });
}

export function getVoiceStatus(): Promise<VoiceStatus> {
  return request("/admin/voice/status");
}

export function getVoicePhrases(): Promise<VoicePhrases> {
  return request("/admin/voice/phrases");
}

export async function postVoiceSample(wav: Blob): Promise<VoiceStatus> {
  const response = await fetch(`${SERVICE_URL}/admin/voice/sample`, {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: wav,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as VoiceStatus;
}

export function postSummarize(messages: Message[], maxTokens = 256): Promise<{ content: string }> {
  return request("/summarize", {
    method: "POST",
    body: JSON.stringify({ messages: messages.map(messageToApi), max_tokens: maxTokens }),
  });
}
