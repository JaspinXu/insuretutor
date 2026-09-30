import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { pageImageUrl, pdfUrl } from "../api";
import { t } from "../i18n";
import type { Lang, Source } from "../types";

interface Props {
  source: Source;
  lang: Lang;
  overridePages: number[];
  onClose: () => void;
}

export default function SourcePanel({ source: s, lang, overridePages, onClose }: Props) {
  const [tab, setTab] = useState<"page" | "text">("page");
  const verified = s.source === "override" || overridePages.includes(s.page);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="source-panel" role="dialog" aria-label={`${t(lang, "source")} ${s.n}`}>
      <header className="panel-head">
        <div>
          <div className="panel-kicker">
            {t(lang, "source")} [{s.n}] · {t(lang, "page", { n: s.page })}
          </div>
          <div className="panel-title">{s.section}</div>
          <div className="muted small">{s.doc_title}</div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label={t(lang, "close")}>
          ×
        </button>
      </header>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "page"} className={tab === "page" ? "active" : ""} onClick={() => setTab("page")}>
          {t(lang, "viewPage")}
        </button>
        <button role="tab" aria-selected={tab === "text"} className={tab === "text" ? "active" : ""} onClick={() => setTab("text")}>
          {t(lang, "viewText")}
        </button>
        <a className="link-btn push" href={pdfUrl(s.doc_id, s.page)} target="_blank" rel="noreferrer">
          {t(lang, "openPdf")} ↗
        </a>
      </div>

      <div className="panel-body">
        {tab === "page" ? (
          <>
            <p className="muted small">{verified ? t(lang, "verifiedPage") : t(lang, "highlightNote")}</p>
            <img className="page-img" src={pageImageUrl(s)} alt={`${s.doc_title} — ${t(lang, "page", { n: s.page })}`} />
          </>
        ) : (
          <div className="markdown passage">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.text}</ReactMarkdown>
          </div>
        )}
      </div>
    </aside>
  );
}
