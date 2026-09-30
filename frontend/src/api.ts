import type { AppConfig, ChatMessage, ConversationSummary, FinalPayload, Lang, Source, Stage } from "./types";

const CLIENT_KEY = "insuretutor.clientId";

/** Anonymous per-browser id; the server scopes conversation history to it. */
export function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    return "anonymous";
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { "X-Client-Id": clientId(), ...extra };
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  config: () => fetch("/api/config").then((r) => json<AppConfig>(r)),
  conversations: () => fetch("/api/conversations", { headers: headers() }).then((r) => json<ConversationSummary[]>(r)),
  conversation: (id: string) =>
    fetch(`/api/conversations/${id}`, { headers: headers() }).then((r) =>
      json<{ conversation: ConversationSummary; messages: StoredMessage[] }>(r),
    ),
  deleteConversation: (id: string) => fetch(`/api/conversations/${id}`, { method: "DELETE", headers: headers() }),
  feedback: (messageId: string, rating: 1 | -1) =>
    fetch(`/api/messages/${messageId}/feedback`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ rating }),
    }),
};

/** Rendered PDF page; pass a chunk id to highlight that passage. */
export function pageUrl(docId: string, page: number, opts: { chunkId?: string; thumb?: boolean } = {}): string {
  const params = new URLSearchParams();
  if (opts.chunkId) params.set("chunk", opts.chunkId);
  if (opts.thumb) params.set("size", "thumb");
  const qs = params.toString();
  return `/api/documents/${encodeURIComponent(docId)}/pages/${page}.png${qs ? `?${qs}` : ""}`;
}

export function pageImageUrl(s: Source, thumb = false): string {
  return pageUrl(s.doc_id, s.page, { chunkId: s.chunk_id, thumb });
}

export function pdfUrl(docId: string, page: number): string {
  return `/api/documents/${encodeURIComponent(docId)}/file#page=${page}`;
}

interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: Record<string, unknown>;
  rating: 1 | -1 | null;
}

/** Rebuild UI messages from the server's stored conversation. */
export function fromStored(messages: StoredMessage[]): ChatMessage[] {
  return messages.map((m) => {
    if (m.role === "user") {
      return { id: m.id, role: "user", content: m.content, redactions: (m.meta.redactions as string[]) ?? [] };
    }
    const final = m.meta as unknown as Omit<FinalPayload, "answer">;
    return {
      id: m.id,
      role: "assistant",
      content: m.content,
      sources: final.sources ?? [],
      final: { ...final, message_id: m.id },
      rating: m.rating,
    };
  });
}

export interface StreamHandlers {
  onMeta: (d: { conversation_id: string; lang: Lang; redactions: string[] }) => void;
  onStatus: (stage: Stage) => void;
  onSources: (sources: Source[]) => void;
  onDelta: (text: string) => void;
  onFinal: (payload: FinalPayload) => void;
  onError: (message: string) => void;
}

/** POST a question and consume the server-sent event stream. */
export async function streamChat(
  body: { message: string; conversation_id?: string | null; ui_lang: Lang },
  h: StreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => null);
    h.onError(detail?.detail ?? `${res.status} ${res.statusText}`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      switch (event) {
        case "meta":
          h.onMeta(payload);
          break;
        case "status":
          h.onStatus(payload.stage);
          break;
        case "sources":
          h.onSources(payload.sources);
          break;
        case "delta":
          h.onDelta(payload.text);
          break;
        case "final":
          h.onFinal(payload);
          break;
        case "error":
          h.onError(payload.message);
          break;
      }
    }
  }
}
