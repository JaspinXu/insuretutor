import {
  Activity,
  BadgeCheck,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Info,
  LifeBuoy,
  LoaderCircle,
  Lock,
  ShieldAlert,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  TriangleAlert,
} from "lucide-react";
import { useState, type CSSProperties, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { pageImageUrl } from "../api";
import { t } from "../i18n";
import type { ChatMessage, FinalPayload, Lang, Source, Stage } from "../types";

interface Props {
  message: ChatMessage;
  lang: Lang;
  onOpenSource: (s: Source) => void;
  onRate: (messageId: string, rating: 1 | -1) => void;
}

const STAGES: Stage[] = ["routing", "retrieving", "generating"];
const TIMING_KEYS = ["input_guard", "route", "retrieve", "generate", "output_guard"];

/** "[2]" in the answer becomes a link we render as a citation chip. */
function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

/** Short plain-text preview of a passage, preferring lines in the reader's language. */
function preview(s: Source, lang: Lang, max = 180): string {
  const lines = s.text
    .replace(/\[Note \d+\]/g, "")
    .split("\n")
    .map((l) => l.replace(/^#+\s*|^[-|]\s*|\|/g, " ").trim())
    .filter((l) => l && !/^[-: ]+$/.test(l));
  const zh = (l: string) => (l.match(/[㐀-鿿]/g)?.length ?? 0) / Math.max(l.length, 1) > 0.3;
  const picked = lines.filter((l) => zh(l) === (lang !== "en"));
  const text = (picked.length ? picked : lines).join(" ");
  return text.length > max ? `${text.slice(0, max).trim()}…` : text;
}

function Notice({ kind, icon, children }: { kind: "info" | "warn" | "shield" | "care"; icon: ReactNode; children: ReactNode }) {
  return (
    <div className={`notice ${kind}`}>
      <span className="notice-icon" aria-hidden>
        {icon}
      </span>
      <span>{children}</span>
    </div>
  );
}

function Citation({ n, source, lang, onOpen, children }: { n: number; source?: Source; lang: Lang; onOpen: (s: Source) => void; children: ReactNode }) {
  // The preview is positioned against the viewport so the scrolling thread can't clip it.
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const show = (e: { currentTarget: HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect();
    const width = 300;
    const left = Math.min(Math.max(12, r.left + r.width / 2 - width / 2), window.innerWidth - width - 12);
    setPos(r.top > 230 ? { left, bottom: window.innerHeight - r.top + 8, width } : { left, top: r.bottom + 8, width });
  };
  return (
    <span className="cite-wrap" onMouseEnter={show} onMouseLeave={() => setPos(null)}>
      <button
        className="cite"
        disabled={!source}
        onClick={() => source && onOpen(source)}
        onFocus={show}
        onBlur={() => setPos(null)}
        aria-label={`${t(lang, "source")} ${n}`}
      >
        {children}
      </button>
      {source && pos && (
        <span className="cite-pop" role="tooltip" style={pos}>
          <span className="cite-pop-head">
            {t(lang, "pageLong", { n: source.page })} · {source.section}
          </span>
          <span className="cite-pop-body">{preview(source, lang)}</span>
        </span>
      )}
    </span>
  );
}

function StageStepper({ stage, lang }: { stage?: Stage; lang: Lang }) {
  const current = stage ? STAGES.indexOf(stage) : 0;
  return (
    <ol className="stepper" aria-label="progress">
      {STAGES.map((s, i) => (
        <li key={s} className={i < current ? "done" : i === current ? "active" : ""}>
          <span className="stepper-dot">
            {i < current ? <Check size={12} strokeWidth={3} /> : i === current ? <LoaderCircle size={12} className="spin" /> : null}
          </span>
          {t(lang, `stage.${s}`)}
        </li>
      ))}
    </ol>
  );
}

function SourceCard({ s, lang, onOpen }: { s: Source; lang: Lang; onOpen: (s: Source) => void }) {
  return (
    <button className="source-card" onClick={() => onOpen(s)} title={s.section}>
      <img src={pageImageUrl(s, true)} alt="" loading="lazy" />
      <span className="source-card-body">
        <span className="source-card-head">
          <span className="source-n">{s.n}</span>
          {t(lang, "pageLong", { n: s.page })}
          {s.source === "override" && <BadgeCheck size={13} className="verified" aria-label="verified" />}
        </span>
        <span className="source-card-section">{s.section}</span>
      </span>
    </button>
  );
}

function Trace({ f, lang }: { f: Omit<FinalPayload, "answer">; lang: Lang }) {
  const m = f.metrics;
  const timings = TIMING_KEYS.map((k) => [k, m.timings[`${k}_ms`]] as const).filter(([, v]) => v !== undefined);
  const max = Math.max(1, ...timings.map(([, v]) => v));
  return (
    <div className="trace">
      <div className="trace-grid">
        <div className="trace-item">
          <span className="trace-label">{t(lang, "intent")}</span>
          <span className="pill">{t(lang, `intent.${f.intent}`)}</span>
          {m.route && <span className="muted small">{t(lang, "routedBy")}: {m.route.source === "llm" ? "LLM" : "heuristic"}</span>}
        </div>
        {m.retrieval && (
          <div className="trace-item">
            <span className="trace-label">{t(lang, "retrieval")}</span>
            <span>{t(lang, m.retrieval.dense ? "hybrid" : "keyword")}</span>
          </div>
        )}
        {m.model && (
          <div className="trace-item">
            <span className="trace-label">{t(lang, "model")}</span>
            <span>
              {m.provider} · {m.model}
            </span>
          </div>
        )}
        {Object.keys(m.usage).length > 0 && (
          <div className="trace-item">
            <span className="trace-label">{t(lang, "tokens")}</span>
            <span>
              {Object.entries(m.usage)
                .map(([k, u]) => `${k} ${u.input_tokens}→${u.output_tokens}`)
                .join(" · ")}
            </span>
          </div>
        )}
      </div>
      {m.retrieval && m.retrieval.queries.length > 0 && (
        <div className="trace-block">
          <span className="trace-label">{t(lang, "queries")}</span>
          <div className="query-chips">
            {m.retrieval.queries.map((q) => (
              <span key={q} className="query-chip">
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="trace-block">
        <span className="trace-label">
          {t(lang, "timings")} · {m.total_ms} ms
        </span>
        <div className="timing-bars">
          {timings.map(([k, v]) => (
            <div key={k} className="timing-row">
              <span className="timing-name">{t(lang, `timing.${k}`)}</span>
              <span className="timing-track">
                <span className={`timing-bar b-${k}`} style={{ width: `${Math.max(2, (v / max) * 100)}%` }} />
              </span>
              <span className="timing-ms">{v} ms</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function verdictIcon(verdict: string) {
  if (verdict === "self_harm") return <LifeBuoy size={16} />;
  if (verdict === "not_found" || verdict === "out_of_scope") return <Info size={16} />;
  return <ShieldAlert size={16} />;
}

export default function MessageView({ message: m, lang, onOpenSource, onRate }: Props) {
  const [showOther, setShowOther] = useState(false);
  const [showTrace, setShowTrace] = useState(false);
  const [copied, setCopied] = useState(false);

  if (m.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{m.content}</div>
        {m.redactions && m.redactions.length > 0 && (
          <Notice kind="shield" icon={<Lock size={14} />}>
            {t(lang, "redacted", { kinds: m.redactions.join(", ") })}
          </Notice>
        )}
      </div>
    );
  }

  const f = m.final;
  const sources = m.sources ?? [];
  const byN = new Map(sources.map((s) => [s.n, s]));
  const cited = f ? sources.filter((s) => f.cited.includes(s.n)) : [];
  const other = f ? sources.filter((s) => !f.cited.includes(s.n)) : [];
  const verdict = f?.guardrail?.verdict;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="msg assistant">
      <div className="avatar" aria-hidden>
        <ShieldCheck size={18} strokeWidth={2.2} />
      </div>
      <div className="assistant-body">
        <div className="assistant-head">
          <span className="assistant-name">{t(lang, "assistant")}</span>
          {f && !verdict && f.intent !== "greeting" && <span className="pill subtle">{t(lang, `intent.${f.intent}`)}</span>}
          {f && (f.mode === "offline" || f.mode === "fallback") && <span className="pill amber">{t(lang, "offlineBadge")}</span>}
        </div>

        {verdict && (
          <Notice kind={verdict === "self_harm" ? "care" : "shield"} icon={verdictIcon(verdict)}>
            {t(lang, `verdict.${verdict}`)}
          </Notice>
        )}

        {m.pending && !m.content && <StageStepper stage={m.stage} lang={lang} />}

        {m.content && (
          <div className={`markdown ${m.pending ? "streaming" : ""}`}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => {
                  const match = href?.match(/^#cite-(\d+)$/);
                  if (match) {
                    const n = Number(match[1]);
                    return (
                      <Citation n={n} source={byN.get(n)} lang={lang} onOpen={onOpenSource}>
                        {children}
                      </Citation>
                    );
                  }
                  return (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  );
                },
              }}
            >
              {linkCitations(m.content)}
            </ReactMarkdown>
          </div>
        )}

        {m.error && (
          <Notice kind="warn" icon={<TriangleAlert size={16} />}>
            {t(lang, "error", { msg: m.error })}
          </Notice>
        )}
        {f && f.unverified_numbers.length > 0 && (
          <Notice kind="warn" icon={<TriangleAlert size={16} />}>
            {t(lang, "unverified", { nums: f.unverified_numbers.join(", ") })}
          </Notice>
        )}
        {f && f.flags.includes("no_citations") && !f.guardrail && (
          <Notice kind="warn" icon={<TriangleAlert size={16} />}>
            {t(lang, "noCitations")}
          </Notice>
        )}
        {f && f.flags.includes("invalid_citations_removed") && (
          <Notice kind="info" icon={<Info size={16} />}>
            {t(lang, "invalidCitations")}
          </Notice>
        )}

        {cited.length > 0 && (
          <div className="sources">
            <div className="section-label">
              {t(lang, "sources")} · {cited.length}
            </div>
            <div className="source-cards">
              {cited.map((s) => (
                <SourceCard key={s.n} s={s} lang={lang} onOpen={onOpenSource} />
              ))}
            </div>
          </div>
        )}

        {other.length > 0 && (
          <div className="sources other">
            <button className="link-btn" onClick={() => setShowOther((v) => !v)} aria-expanded={showOther}>
              {showOther ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {t(lang, "otherSources", { n: other.length })}
            </button>
            {showOther && (
              <div className="source-cards">
                {other.map((s) => (
                  <SourceCard key={s.n} s={s} lang={lang} onOpen={onOpenSource} />
                ))}
              </div>
            )}
          </div>
        )}

        {f && !m.pending && (
          <div className="msg-actions">
            <button className="action" onClick={copy} title={t(lang, copied ? "copied" : "copy")}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
            <button className={`action ${m.rating === 1 ? "on" : ""}`} onClick={() => onRate(f.message_id, 1)} title={t(lang, "helpful")} aria-label={t(lang, "helpful")}>
              <ThumbsUp size={15} />
            </button>
            <button className={`action ${m.rating === -1 ? "on" : ""}`} onClick={() => onRate(f.message_id, -1)} title={t(lang, "notHelpful")} aria-label={t(lang, "notHelpful")}>
              <ThumbsDown size={15} />
            </button>
            <button className="link-btn trace-toggle" onClick={() => setShowTrace((v) => !v)} aria-expanded={showTrace}>
              <Activity size={14} /> {t(lang, "details")} {showTrace ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        )}

        {showTrace && f && <Trace f={f} lang={lang} />}
      </div>
    </div>
  );
}
