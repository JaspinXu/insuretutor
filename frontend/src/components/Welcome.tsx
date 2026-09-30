import { t } from "../i18n";
import type { AppConfig, Lang } from "../types";

interface Props {
  lang: Lang;
  config: AppConfig | null;
  onAsk: (q: string) => void;
}

export default function Welcome({ lang, config, onAsk }: Props) {
  const suggestions = config?.suggestions[lang] ?? [];
  return (
    <div className="welcome">
      <h1>{t(lang, "welcomeTitle")}</h1>
      <p className="muted">{t(lang, "welcomeBody")}</p>

      {suggestions.length > 0 && (
        <>
          <h2 className="section-label">{t(lang, "tryAsking")}</h2>
          <div className="suggestions">
            {suggestions.map((s) => (
              <button key={s} className="suggestion" onClick={() => onAsk(s)}>
                {s}
              </button>
            ))}
          </div>
        </>
      )}

      {config && config.documents.length > 0 && (
        <>
          <h2 className="section-label">{t(lang, "documents")}</h2>
          <div className="doc-cards">
            {config.documents.map((d) => (
              <a key={d.id} className="doc-card" href={`/api/documents/${d.id}/file`} target="_blank" rel="noreferrer">
                <div className="doc-icon" aria-hidden>
                  PDF
                </div>
                <div>
                  <div className="doc-title">{d.title[lang] ?? d.title.en}</div>
                  <div className="muted small">
                    {d.insurer} · {d.product_type}
                  </div>
                  <div className="muted small">
                    {d.doc_type} · {d.version} · {t(lang, "pages", { n: d.pages })}
                  </div>
                </div>
              </a>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
