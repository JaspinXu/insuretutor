import { MessageSquareText, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { pageUrl } from "../api";
import { locale, t } from "../i18n";
import type { AppConfig, ConversationSummary, Lang } from "../types";

interface Props {
  lang: Lang;
  config: AppConfig | null;
  open: boolean;
  conversations: ConversationSummary[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

function when(ts: number, lang: Lang): string {
  const d = new Date(ts * 1000);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString(locale(lang), { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(locale(lang), { month: "short", day: "numeric" });
}

export default function Sidebar({ lang, config, open, conversations, activeId, onNew, onOpen, onDelete, onClose }: Props) {
  const doc = config?.documents[0];
  const online = config && config.provider !== "offline";
  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-head">
          <div className="logo" aria-hidden>
            <ShieldCheck size={20} strokeWidth={2.2} />
          </div>
          <div className="brand-text">
            <div className="brand-name">InsureTutor</div>
            <div className="brand-tagline">{t(lang, "tagline")}</div>
          </div>
          <button className="icon-btn sidebar-close" onClick={onClose} aria-label={t(lang, "close")}>
            <X size={18} />
          </button>
        </div>

        <button className="new-chat" onClick={onNew}>
          <Plus size={18} /> {t(lang, "newChat")}
        </button>

        <div className="sidebar-label">{t(lang, "recent")}</div>
        <nav className="conv-list">
          {conversations.length === 0 && <p className="conv-empty">{t(lang, "noHistory")}</p>}
          {conversations.map((c) => (
            <div key={c.id} className={`conv-item ${c.id === activeId ? "active" : ""}`}>
              <button className="conv-open" onClick={() => onOpen(c.id)} title={c.title}>
                <MessageSquareText size={15} className="conv-icon" aria-hidden />
                <span className="conv-title">{c.title}</span>
                <span className="conv-time">{when(c.updated_at, lang)}</span>
              </button>
              <button className="conv-del" onClick={() => onDelete(c.id)} aria-label={t(lang, "delete")} title={t(lang, "delete")}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          {doc && (
            <a className="doc-mini" href={`/api/documents/${doc.id}/file`} target="_blank" rel="noreferrer" title={doc.title[lang] ?? doc.title.en}>
              <img src={pageUrl(doc.id, 1, { thumb: true })} alt="" loading="lazy" />
              <div>
                <div className="doc-mini-title">{doc.title[lang] ?? doc.title.en}</div>
                <div className="doc-mini-meta">
                  {doc.doc_type} · {t(lang, "pages", { n: doc.pages })}
                </div>
              </div>
            </a>
          )}
          {config && (
            <div className={`status ${online ? "online" : "offline"}`}>
              <span className="dot" aria-hidden />
              {online ? t(lang, "statusLlm", { model: config.model ?? config.provider }) : t(lang, "statusOffline")}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
