import { ArrowUp, Square } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import { t } from "../i18n";
import type { Lang } from "../types";

interface Props {
  lang: Lang;
  busy: boolean;
  maxChars: number;
  onSend: (text: string) => void;
  onStop: () => void;
}

export default function Composer({ lang, busy, maxChars, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const composing = useRef(false); // IME (pinyin / cangjie) composition in progress

  const submit = () => {
    const value = text.trim();
    if (!value || busy || value.length > maxChars) return;
    onSend(value);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter confirms an IME candidate while composing Chinese — don't send then.
    if (e.key === "Enter" && !e.shiftKey && !composing.current && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const over = text.length > maxChars;
  return (
    <div className={`composer ${over ? "over" : ""}`}>
      <textarea
        value={text}
        rows={1}
        placeholder={t(lang, "placeholder")}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onCompositionStart={() => (composing.current = true)}
        onCompositionEnd={() => (composing.current = false)}
        aria-label={t(lang, "placeholder")}
      />
      <div className="composer-row">
        <span className="composer-hint">{t(lang, "hint")}</span>
        {text.length > maxChars * 0.8 && (
          <span className={`counter ${over ? "danger" : ""}`}>
            {text.length}/{maxChars}
          </span>
        )}
        {busy ? (
          <button className="send-btn stop" onClick={onStop} aria-label={t(lang, "stop")} title={t(lang, "stop")}>
            <Square size={14} fill="currentColor" />
          </button>
        ) : (
          <button
            className="send-btn"
            onClick={submit}
            disabled={!text.trim() || over}
            aria-label={t(lang, "send")}
            title={t(lang, "send")}
          >
            <ArrowUp size={18} strokeWidth={2.4} />
          </button>
        )}
      </div>
    </div>
  );
}
