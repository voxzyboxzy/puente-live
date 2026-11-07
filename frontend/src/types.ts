export type Lang = "en" | "es";

export type GraphNode = {
  id: string;
  status: "idle" | "active" | "ok" | "fail" | "info" | string;
  title_en: string;
  title_es: string;
  detail_en: string;
  detail_es: string;
};

export type GraphEdge = [string, string];

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  phase?: string;
};

export type Session = {
  id: string;
  phase: string;
  scenario_id: string | null;
  scenario_title_en?: string | null;
  scenario_title_es?: string | null;
  language: Lang;
  language_confidence?: number;
  language_path: string[];
  reported_polarities: Record<string, string>;
  error_codes: string[];
  devices: string[];
  phase_log: { from: string; event: string; to: string }[];
  steps_done: string[];
  steps_total: number;
  current_step: string | null;
  failures: number;
  technician: { tech_id: string; note: string } | null;
  redaction_count: number;
  resolution: string | null;
  ticket_id: string | null;
  llm_mode: string;
  provider: string;
  created_at?: string;
};

export type Utterance = {
  id?: number;
  role: string;
  text: string;
  language?: string;
  phase?: string;
  redaction_count?: number;
  interrupted?: number | boolean;
};

export type Citation = {
  id: string;
  title: string;
  excerpt: string;
  source_label: string;
  overlap: number;
  language: string;
};

export type ToolResult = {
  tool: string;
  ok: boolean;
  summary_en: string;
  summary_es: string;
  safe?: boolean;
};

export type Ticket = {
  ticket_id: string;
  status: string;
  markdown?: string;
  error_codes?: string[];
  devices?: string[];
  reported_polarities?: Record<string, string>;
  redaction_count?: number;
  scenario_id?: string | null;
  synthetic?: boolean;
};

export type ScenarioCard = {
  id: string;
  title_en: string;
  title_es: string;
  prompt_en: string;
  prompt_es: string;
};

export type BridgePack = {
  session: Session;
  assistant_text?: string;
  language?: Lang;
  citations?: Citation[];
  tools?: ToolResult[];
  graph?: Graph;
  phase?: string;
  ticket?: Ticket | null;
  transcript?: Utterance[];
};
