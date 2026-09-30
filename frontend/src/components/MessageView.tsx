import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { t } from "../i18n";
import type { ChatMessage, Lang, Source } from "../types";

interface Props {
  message: ChatMessage;
  lang: Lang;
  onOpenSource: (s: Source) => void;
  onRate: (messageId: string, rating: 1 | -1) => void;
}

/** "[2]" in the answer becomes a link we render as a clickable citation chip. */
function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

function SourceChip({ s, lang, onOpen }: { s: Source; lang: Lang; onOpen: (s: Source) => void }) {
  return (
    <button className="source-chip" onClick={() => onOpen(s)} title={s.section}>
      <span className="source-n">{s.n}</span>
      <span className="source-page">{t(lang, "page", { n: s.page })}</span>
      <span className="source-section">{s.section}</span>
    </button>
  );
}

function Notice({ kind, children }: { kind: "info" | "warn" | "shield"; children: ReactNode }) {
  const icon = kind === "shield" ? "🛡" : kind === "warn" ? "⚠" : "ℹ";
  return (
    <div className={`notice ${kind}`}>
      <span aria-hidden>{icon}</span>
      <span>{children}</span>
    </div>
  );
}

export default function MessageView({ message: m, lang, onOpenSource, onRate }: Props) {
  const [showOther, setShowOther] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  if (m.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{m.content}</div>
        {m.redactions && m.redactions.length > 0 && (
          <Notice kind="shield">{t(lang, "redacted", { kinds: m.redactions.join(", ") })}</Notice>
        )}
      </div>
    );
  }

  const f = m.final;
  const sources = m.sources ?? [];
  const byN = new Map(sources.map((s) => [s.n, s]));
  const cited = f ? sources.filter((s) => f.cited.includes(s.n)) : [];
  const other = f ? sources.filter((s) => !f.cited.includes(s.n)) : [];
  const metrics = f?.metrics;

  return (
    <div className="msg assistant">
      <div className="avatar" aria-hidden>
        ✓
      </div>
      <div className="assistant-body">
        {f?.guardrail && (
          <Notice kind="shield">
            {t(lang, "guardrail")} · {t(lang, `verdict.${f.guardrail.verdict}`)}
          </Notice>
        )}
        {f?.mode === "offline" && <Notice kind="info">{t(lang, "offline")}</Notice>}
        {f?.mode === "fallback" && <Notice kind="warn">{t(lang, "fallback")}</Notice>}

        {m.pending && !m.content && (
          <div className="thinking">
            <span className="dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            {m.stage && t(lang, `stage.${m.stage}`)}
          </div>
        )}

        {m.content && (
          <div className={`markdown ${m.pending ? "streaming" : ""}`}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => {
                  const match = href?.match(/^#cite-(\d+)$/);
                  if (match) {
                    const s = byN.get(Number(match[1]));
                    return (
                      <button
                        className="cite"
                        disabled={!s}
                        onClick={() => s && onOpenSource(s)}
                        title={s ? `${t(lang, "page", { n: s.page })} · ${s.section}` : undefined}
                      >
                        {children}
                      </button>
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

        {m.error && <Notice kind="warn">{t(lang, "error", { msg: m.error })}</Notice>}

        {f && f.unverified_numbers.length > 0 && (
          <Notice kind="warn">{t(lang, "unverified", { nums: f.unverified_numbers.join(", ") })}</Notice>
        )}
        {f && f.flags.includes("no_citations") && !f.guardrail && <Notice kind="warn">{t(lang, "noCitations")}</Notice>}
        {f && f.flags.includes("invalid_citations_removed") && <Notice kind="info">{t(lang, "invalidCitations")}</Notice>}

        {cited.length > 0 && (
          <div className="sources">
            <div className="section-label">{t(lang, "sources")}</div>
            <div className="source-list">
              {cited.map((s) => (
                <SourceChip key={s.n} s={s} lang={lang} onOpen={onOpenSource} />
              ))}
            </div>
          </div>
        )}

        {other.length > 0 && (
          <div className="sources other">
            <button className="link-btn" onClick={() => setShowOther((v) => !v)} aria-expanded={showOther}>
              {showOther ? "▾" : "▸"} {t(lang, "otherSources", { n: other.length })}
            </button>
            {showOther && (
              <div className="source-list">
                {other.map((s) => (
                  <SourceChip key={s.n} s={s} lang={lang} onOpen={onOpenSource} />
                ))}
              </div>
            )}
          </div>
        )}

        {f && !m.pending && (
          <div className="msg-actions">
            <button
              className={`icon-btn ${m.rating === 1 ? "on" : ""}`}
              onClick={() => onRate(f.message_id, 1)}
              aria-label={t(lang, "helpful")}
              title={t(lang, "helpful")}
            >
              👍
            </button>
            <button
              className={`icon-btn ${m.rating === -1 ? "on" : ""}`}
              onClick={() => onRate(f.message_id, -1)}
              aria-label={t(lang, "notHelpful")}
              title={t(lang, "notHelpful")}
            >
              👎
            </button>
            {metrics && (
              <button className="link-btn" onClick={() => setShowDetails((v) => !v)} aria-expanded={showDetails}>
                {showDetails ? "▾" : "▸"} {t(lang, "details")}
              </button>
            )}
          </div>
        )}

        {showDetails && metrics && (
          <dl className="details">
            <dt>{t(lang, "intent")}</dt>
            <dd>
              {t(lang, `intent.${f!.intent}`)}
              {metrics.route && <span className="muted"> · {metrics.route.source}</span>}
            </dd>
            {metrics.retrieval && (
              <>
                <dt>{t(lang, "retrieval")}</dt>
                <dd>{t(lang, metrics.retrieval.dense ? "hybrid" : "keyword")}</dd>
                <dt>{t(lang, "queries")}</dt>
                <dd>
                  <ul>
                    {metrics.retrieval.queries.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </dd>
              </>
            )}
            <dt>{t(lang, "timings")}</dt>
            <dd>
              {Object.entries(metrics.timings)
                .map(([k, v]) => `${k.replace(/_ms$/, "")} ${v} ms`)
                .join(" · ")}{" "}
              · total {metrics.total_ms} ms
            </dd>
            {Object.keys(metrics.usage).length > 0 && (
              <>
                <dt>{t(lang, "tokens")}</dt>
                <dd>
                  {Object.entries(metrics.usage)
                    .map(([k, u]) => `${k}: ${u.input_tokens} in / ${u.output_tokens} out`)
                    .join(" · ")}
                </dd>
              </>
            )}
            {metrics.model && (
              <>
                <dt>{t(lang, "model")}</dt>
                <dd>
                  {metrics.provider} · {metrics.model}
                </dd>
              </>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}
