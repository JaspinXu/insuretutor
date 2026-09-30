export type Lang = "en" | "zh-Hans" | "zh-Hant";

export interface Source {
  n: number;
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  page: number;
  section: string;
  text: string;
  lang: string;
  source: "extracted" | "override";
  score: number;
  bm25: number;
  dense: number | null;
  cited?: boolean;
}

export interface Guardrail {
  stage: "input" | "router" | "retrieval" | "generation" | "output";
  verdict: string;
  matched?: string | null;
}

export interface Metrics {
  timings: Record<string, number>;
  total_ms: number;
  usage: Record<string, { input_tokens: number; output_tokens: number }>;
  model: string | null;
  provider: string;
  route?: {
    intent: string;
    source: string;
    standalone_question: string;
    search_queries: string[];
    reason: string;
  };
  retrieval?: { queries: string[]; dense: boolean; best_bm25: number };
}

/** The validated result of one assistant turn (SSE `final` event / stored meta). */
export interface FinalPayload {
  message_id: string;
  conversation_id: string;
  answer: string;
  lang: Lang;
  intent: string;
  mode: string;
  sources: Source[];
  cited: number[];
  flags: string[];
  unverified_numbers: string[];
  guardrail: Guardrail | null;
  redactions: string[];
  metrics: Metrics;
}

export type Stage = "routing" | "retrieving" | "generating";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  stage?: Stage;
  sources?: Source[];
  final?: Omit<FinalPayload, "answer">;
  rating?: 1 | -1 | null;
  error?: string;
  redactions?: string[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  lang: Lang;
  created_at: number;
  updated_at: number;
}

export interface DocumentInfo {
  id: string;
  title: Record<string, string>;
  insurer: string;
  product_type: string;
  doc_type: string;
  version: string;
  pages: number;
  override_pages: number[];
}

export interface AppConfig {
  provider: string;
  model: string | null;
  dense_retrieval: boolean;
  max_input_chars: number;
  suggestions: Record<Lang, string[]>;
  documents: DocumentInfo[];
}
