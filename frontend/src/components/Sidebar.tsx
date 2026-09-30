import { t } from "../i18n";
import type { ConversationSummary, Lang } from "../types";

interface Props {
  lang: Lang;
  open: boolean;
  conversations: ConversationSummary[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

function when(ts: number, lang: Lang): string {
  const locale = lang === "en" ? "en-GB" : lang === "zh-Hans" ? "zh-CN" : "zh-HK";
  return new Date(ts * 1000).toLocaleString(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function Sidebar({ lang, open, conversations, activeId, onNew, onOpen, onDelete, onClose }: Props) {
  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <button className="primary-btn new-chat" onClick={onNew}>
          + {t(lang, "newChat")}
        </button>
        <h2 className="sidebar-title">{t(lang, "history")}</h2>
        <nav className="conv-list">
          {conversations.length === 0 && <p className="muted small">{t(lang, "noHistory")}</p>}
          {conversations.map((c) => (
            <div key={c.id} className={`conv-item ${c.id === activeId ? "active" : ""}`}>
              <button className="conv-open" onClick={() => onOpen(c.id)} title={c.title}>
                <span className="conv-title">{c.title}</span>
                <span className="conv-time">{when(c.updated_at, lang)}</span>
              </button>
              <button className="icon-btn conv-del" onClick={() => onDelete(c.id)} aria-label={t(lang, "delete")} title={t(lang, "delete")}>
                ×
              </button>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
