import { BadgeCheck, ChevronLeft, ChevronRight, ExternalLink, Highlighter, X, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { pageImageUrl, pageUrl, pdfUrl } from "../api";
import { t } from "../i18n";
import type { DocumentInfo, Lang, Source } from "../types";

interface Props {
  source: Source;
  lang: Lang;
  document: DocumentInfo | null;
  onClose: () => void;
}

export default function SourcePanel({ source: s, lang, document: doc, onClose }: Props) {
  const [tab, setTab] = useState<"page" | "text">("page");
  const [page, setPage] = useState(s.page);
  const [zoom, setZoom] = useState(false);
  const pageCount = doc?.pages ?? s.page;
  const verified = s.source === "override" || (doc?.override_pages ?? []).includes(s.page);
  const onCitedPage = page === s.page;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (tab === "page" && e.key === "ArrowLeft") setPage((p) => Math.max(1, p - 1));
      if (tab === "page" && e.key === "ArrowRight") setPage((p) => Math.min(pageCount, p + 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, tab, pageCount]);

  return (
    <aside className="source-panel" role="dialog" aria-label={`${t(lang, "source")} ${s.n}`}>
      <header className="panel-head">
        <div className="panel-titles">
          <div className="panel-kicker">
            <span className="source-n">{s.n}</span>
            {t(lang, "source")} · {t(lang, "pageLong", { n: s.page })}
          </div>
          <div className="panel-title">{s.section}</div>
          <div className="panel-doc">{s.doc_title}</div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label={t(lang, "close")}>
          <X size={18} />
        </button>
      </header>

      <div className="panel-toolbar">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "page"} className={tab === "page" ? "active" : ""} onClick={() => setTab("page")}>
            {t(lang, "viewPage")}
          </button>
          <button role="tab" aria-selected={tab === "text"} className={tab === "text" ? "active" : ""} onClick={() => setTab("text")}>
            {t(lang, "viewText")}
          </button>
        </div>
        {tab === "page" && (
          <div className="pager">
            <button className="icon-btn" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} aria-label={t(lang, "prevPage")}>
              <ChevronLeft size={16} />
            </button>
            <span className="pager-label">
              {page} / {pageCount}
            </span>
            <button className="icon-btn" onClick={() => setPage((p) => Math.min(pageCount, p + 1))} disabled={page >= pageCount} aria-label={t(lang, "nextPage")}>
              <ChevronRight size={16} />
            </button>
            <button className="icon-btn" onClick={() => setZoom((z) => !z)} aria-label={t(lang, zoom ? "zoomOut" : "zoomIn")} title={t(lang, zoom ? "zoomOut" : "zoomIn")}>
              {zoom ? <ZoomOut size={16} /> : <ZoomIn size={16} />}
            </button>
          </div>
        )}
        <a className="icon-btn" href={pdfUrl(s.doc_id, page)} target="_blank" rel="noreferrer" title={t(lang, "openPdf")} aria-label={t(lang, "openPdf")}>
          <ExternalLink size={16} />
        </a>
      </div>

      <div className="panel-body">
        {tab === "page" ? (
          <>
            <p className="panel-note">
              {!onCitedPage ? (
                t(lang, "otherPageNote", { n: s.page })
              ) : verified ? (
                <>
                  <BadgeCheck size={14} /> {t(lang, "verifiedPage")}
                </>
              ) : (
                <>
                  <Highlighter size={14} /> {t(lang, "highlightNote")}
                </>
              )}
            </p>
            <div className={`page-frame ${zoom ? "zoomed" : ""}`}>
              <img
                className="page-img"
                src={onCitedPage ? pageImageUrl(s) : pageUrl(s.doc_id, page)}
                alt={`${s.doc_title} — ${t(lang, "pageLong", { n: page })}`}
              />
            </div>
          </>
        ) : (
          <blockquote className="markdown passage">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.text}</ReactMarkdown>
          </blockquote>
        )}
      </div>
    </aside>
  );
}
