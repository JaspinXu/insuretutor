import { useCallback, useEffect, useRef, useState } from "react";
import { api, fromStored, streamChat } from "./api";
import Composer from "./components/Composer";
import MessageView from "./components/MessageView";
import Sidebar from "./components/Sidebar";
import SourcePanel from "./components/SourcePanel";
import Welcome from "./components/Welcome";
import { LANG_LABELS, detectUiLang, t } from "./i18n";
import type { AppConfig, ChatMessage, ConversationSummary, Lang, Source } from "./types";

const LANG_KEY = "insuretutor.uiLang";

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY) as Lang | null;
    if (saved === "en" || saved === "zh-Hans" || saved === "zh-Hant") return saved;
  } catch {
    /* storage unavailable */
  }
  return detectUiLang();
}

export default function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      /* ignore */
    }
  }, [lang]);

  const refreshConversations = useCallback(() => {
    api.conversations().then(setConversations).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const updateLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => (prev.length ? [...prev.slice(0, -1), fn(prev[prev.length - 1])] : prev));

  const send = async (text: string) => {
    if (busy || !text.trim()) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: "user", content: text },
      { id: `a-${Date.now()}`, role: "assistant", content: "", pending: true, stage: "routing" },
    ]);
    try {
      await streamChat(
        { message: text, conversation_id: conversationId, ui_lang: lang },
        {
          onMeta: (d) => {
            setConversationId(d.conversation_id);
            if (d.redactions.length) {
              setMessages((prev) => {
                const copy = [...prev];
                const userIdx = copy.length - 2;
                if (userIdx >= 0) copy[userIdx] = { ...copy[userIdx], redactions: d.redactions };
                return copy;
              });
            }
          },
          onStatus: (stage) => updateLast((m) => ({ ...m, stage })),
          onSources: (sources) => updateLast((m) => ({ ...m, sources })),
          onDelta: (delta) => updateLast((m) => ({ ...m, content: m.content + delta })),
          onFinal: (payload) => {
            const { answer, ...final } = payload;
            updateLast((m) => ({
              ...m,
              id: payload.message_id,
              content: answer,
              pending: false,
              sources: payload.sources,
              final,
            }));
            refreshConversations();
          },
          onError: (msg) => updateLast((m) => ({ ...m, pending: false, error: msg })),
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        updateLast((m) => ({ ...m, pending: false, error: (err as Error).message }));
      } else {
        updateLast((m) => ({ ...m, pending: false }));
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
      updateLast((m) => (m.pending ? { ...m, pending: false } : m));
    }
  };

  const stop = () => abortRef.current?.abort();

  const newChat = () => {
    stop();
    setConversationId(null);
    setMessages([]);
    setOpenSource(null);
    setSidebarOpen(false);
  };

  const openConversation = async (id: string) => {
    stop();
    setSidebarOpen(false);
    setOpenSource(null);
    const data = await api.conversation(id);
    setConversationId(id);
    setMessages(fromStored(data.messages));
  };

  const deleteConversation = async (id: string) => {
    await api.deleteConversation(id);
    if (id === conversationId) newChat();
    refreshConversations();
  };

  const rate = async (messageId: string, rating: 1 | -1) => {
    await api.feedback(messageId, rating);
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, rating } : m)));
  };

  const providerBadge = !config
    ? ""
    : config.provider === "offline"
      ? t(lang, "offlineBadge")
      : `${config.provider} · ${config.model ?? ""}`;

  return (
    <div className="app">
      <Sidebar
        lang={lang}
        open={sidebarOpen}
        conversations={conversations}
        activeId={conversationId}
        onNew={newChat}
        onOpen={openConversation}
        onDelete={deleteConversation}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label={t(lang, "menu")}>
            ☰
          </button>
          <div className="brand">
            <span className="brand-mark" aria-hidden>
              ✓
            </span>
            <div>
              <div className="brand-name">InsureTutor</div>
              <div className="brand-sub">{t(lang, "subtitle")}</div>
            </div>
          </div>
          <div className="topbar-right">
            {providerBadge && <span className={`badge ${config?.provider === "offline" ? "warn" : ""}`}>{providerBadge}</span>}
            <div className="lang-switch" role="group" aria-label="Language">
              {(Object.keys(LANG_LABELS) as Lang[]).map((l) => (
                <button key={l} className={l === lang ? "active" : ""} onClick={() => setLang(l)} aria-pressed={l === lang}>
                  {LANG_LABELS[l]}
                </button>
              ))}
            </div>
          </div>
        </header>

        <section className="thread" aria-live="polite">
          {messages.length === 0 ? (
            <Welcome lang={lang} config={config} onAsk={send} />
          ) : (
            messages.map((m) => (
              <MessageView key={m.id} message={m} lang={lang} onOpenSource={setOpenSource} onRate={rate} />
            ))
          )}
          <div ref={bottomRef} />
        </section>

        <footer className="footer">
          <Composer lang={lang} busy={busy} maxChars={config?.max_input_chars ?? 2000} onSend={send} onStop={stop} />
          <p className="disclaimer">{t(lang, "disclaimer")}</p>
        </footer>
      </main>

      {openSource && (
        <SourcePanel
          source={openSource}
          lang={lang}
          overridePages={config?.documents.find((d) => d.id === openSource.doc_id)?.override_pages ?? []}
          onClose={() => setOpenSource(null)}
        />
      )}
    </div>
  );
}
