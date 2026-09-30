import {
  ArrowRight,
  BadgeCheck,
  Briefcase,
  Coins,
  FileSearch,
  HeartHandshake,
  Languages,
  MessageSquareText,
  Percent,
  Search,
  ShieldCheck,
  Umbrella,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { pageUrl } from "../api";
import { t } from "../i18n";
import type { AppConfig, Lang } from "../types";

const TOPIC_ICONS: Record<string, LucideIcon> = {
  death: Umbrella,
  gio: HeartHandshake,
  fees: Coins,
  job: Briefcase,
  rates: Percent,
  cooling: Undo2,
};

interface Props {
  lang: Lang;
  config: AppConfig | null;
  onAsk: (q: string) => void;
}

export default function Welcome({ lang, config, onAsk }: Props) {
  const suggestions = config?.suggestions[lang] ?? [];
  const doc = config?.documents[0];
  return (
    <div className="welcome">
      <section className="hero">
        <div className="hero-text">
          <h2>{t(lang, "heroTitle")}</h2>
          <p>{t(lang, "heroBody")}</p>
          <ul className="features">
            <li>
              <FileSearch size={16} /> {t(lang, "featureCite")}
            </li>
            <li>
              <Languages size={16} /> {t(lang, "featureLang")}
            </li>
            <li>
              <ShieldCheck size={16} /> {t(lang, "featureGuard")}
            </li>
          </ul>
        </div>
        {doc && (
          <a className="hero-doc" href={`/api/documents/${doc.id}/file`} target="_blank" rel="noreferrer">
            <img src={pageUrl(doc.id, 1, { thumb: true })} alt={doc.title[lang] ?? doc.title.en} />
            <div className="hero-doc-caption">
              <strong>{doc.title[lang] ?? doc.title.en}</strong>
              <span>
                {doc.insurer.split(" (")[0]} · {t(lang, "pages", { n: doc.pages })}
              </span>
            </div>
          </a>
        )}
      </section>

      {suggestions.length > 0 && (
        <section>
          <h3 className="section-label">{t(lang, "tryAsking")}</h3>
          <div className="topics">
            {suggestions.map((s) => {
              const Icon = TOPIC_ICONS[s.topic] ?? MessageSquareText;
              return (
                <button key={s.question} className="topic" onClick={() => onAsk(s.question)}>
                  <span className={`topic-icon t-${s.topic}`}>
                    <Icon size={18} />
                  </span>
                  <span className="topic-body">
                    <span className="topic-label">{t(lang, `topic.${s.topic}`)}</span>
                    <span className="topic-q">{s.question}</span>
                  </span>
                  <ArrowRight size={16} className="topic-arrow" aria-hidden />
                </button>
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h3 className="section-label">{t(lang, "howItWorks")}</h3>
        <ol className="steps">
          <li>
            <span className="step-icon">
              <Search size={18} />
            </span>
            <strong>{t(lang, "stepSearch")}</strong>
            <span>{t(lang, "stepSearchBody")}</span>
          </li>
          <li>
            <span className="step-icon">
              <MessageSquareText size={18} />
            </span>
            <strong>{t(lang, "stepAnswer")}</strong>
            <span>{t(lang, "stepAnswerBody")}</span>
          </li>
          <li>
            <span className="step-icon">
              <BadgeCheck size={18} />
            </span>
            <strong>{t(lang, "stepVerify")}</strong>
            <span>{t(lang, "stepVerifyBody")}</span>
          </li>
        </ol>
      </section>
    </div>
  );
}
