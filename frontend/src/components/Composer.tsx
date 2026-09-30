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
      <div className="composer-side">
        {text.length > maxChars * 0.8 && (
          <span className={`counter ${over ? "danger" : ""}`}>
            {text.length}/{maxChars}
          </span>
        )}
        {busy ? (
          <button className="primary-btn" onClick={onStop}>
            {t(lang, "stop")}
          </button>
        ) : (
          <button className="primary-btn" onClick={submit} disabled={!text.trim() || over}>
            {t(lang, "send")}
          </button>
        )}
      </div>
    </div>
  );
}
