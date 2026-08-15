export type Role = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
  toolCallId?: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export function messageToApi(m: Message): Record<string, unknown> {
  const out: Record<string, unknown> = { role: m.role, content: m.content };
  if (m.toolCalls) out.tool_calls = m.toolCalls;
  if (m.toolCallId) out.tool_call_id = m.toolCallId;
  return out;
}

export interface Proposal {
  path: string;
  new_text: string;
  summary: string;
  diff: string;
  before: string;
  after: string;
  old: string;
}

export type StepKind = "tool_call" | "tool_result" | "proposal" | "answer" | "stopped";

export interface Step {
  kind: StepKind;
  text: string;
  name: string;
  proposal?: Proposal;
  callId?: string;
  history?: Message[];
}

export interface HealthStatus {
  status: string;
  model_loaded: boolean;
  model: string | null;
}

export interface ModelStatus {
  name?: string;
  agent?: boolean;
  source?: string;
  context_tokens?: number;
  bible_strategy?: string;
  history_window?: number;
  loaded?: boolean;
  detail?: string;
  mode?: string;
  vram_needed?: string;
  vram_available?: string;
  placement_error?: string;
}

export interface ChatResponse {
  content: string;
  reasoning: string;
  tool_calls: { id: string; type: "function"; function: { name: string; arguments: string } }[];
  prompt_tokens: number;
  completion_tokens: number;
}

export interface StoryRouteResponse {
  branch: "new" | "append" | "amend" | "duplicate";
  story_id: string;
  story_title: string;
  event_id: string;
  text: string;
  runners_up: { story_id: string; score: number }[];
}

export interface ToolResponse {
  result: string | null;
  proposal: Proposal | null;
}

export interface SnapshotEntry {
  name: string;
  summary: string;
}

export interface VoiceStatus {
  status: string | null;
}

export interface VoicePhrases {
  languages: [string, string][];
  phrases: Record<string, string>;
}
