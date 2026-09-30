import { Languages, Menu } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
  const threadRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

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

  // Follow the stream only while the reader is at the bottom of the thread.
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const el = threadRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const updateLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => (prev.length ? [...prev.slice(0, -1), fn(prev[prev.length - 1])] : prev));

  const send = async (text: string) => {
    if (busy || !text.trim()) return;
    const controller = new AbortController();
    abortRef.current = controller;
    stickToBottom.current = true;
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
      const aborted = (err as Error).name === "AbortError";
      updateLast((m) => ({ ...m, pending: false, error: aborted ? undefined : (err as Error).message }));
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
    stickToBottom.current = true;
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

  const title = conversations.find((c) => c.id === conversationId)?.title ?? t(lang, "newConversation");
  const empty = messages.length === 0;

  return (
    <div className={`app ${openSource ? "with-panel" : ""}`}>
      <Sidebar
        lang={lang}
        config={config}
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
            <Menu size={20} />
          </button>
          <h1 className="topbar-title" title={title}>
            {empty ? "" : title}
          </h1>
          <div className="lang-switch" role="group" aria-label={t(lang, "language")}>
            <Languages size={16} className="lang-icon" aria-hidden />
            {(Object.keys(LANG_LABELS) as Lang[]).map((l) => (
              <button key={l} className={l === lang ? "active" : ""} onClick={() => setLang(l)} aria-pressed={l === lang}>
                {LANG_LABELS[l]}
              </button>
            ))}
          </div>
        </header>

        <section className="thread" ref={threadRef} onScroll={onScroll} aria-live="polite">
          <div className="thread-inner">
            {empty ? (
              <Welcome lang={lang} config={config} onAsk={send} />
            ) : (
              messages.map((m) => (
                <MessageView key={m.id} message={m} lang={lang} onOpenSource={setOpenSource} onRate={rate} />
              ))
            )}
          </div>
        </section>

        <footer className="footer">
          <Composer lang={lang} busy={busy} maxChars={config?.max_input_chars ?? 2000} onSend={send} onStop={stop} />
          <p className="disclaimer">{t(lang, "disclaimer")}</p>
        </footer>
      </main>

      {openSource && (
        <SourcePanel
          key={openSource.chunk_id}
          source={openSource}
          lang={lang}
          document={config?.documents.find((d) => d.id === openSource.doc_id) ?? null}
          onClose={() => setOpenSource(null)}
        />
      )}
    </div>
  );
}
