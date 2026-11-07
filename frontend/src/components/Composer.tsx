import { useEffect, useRef } from "react";
import type { Lang } from "../types";

export function Composer({
  lang,
  value,
  interim,
  placeholder,
  sendLabel,
  interruptLabel,
  micLabel,
  listening,
  sttReady,
  pending,
  onChange,
  onSend,
  onInterrupt,
  onMic,
}: {
  lang: Lang;
  value: string;
  interim: string;
  placeholder: string;
  sendLabel: string;
  interruptLabel: string;
  micLabel: string;
  listening: boolean;
  sttReady: boolean;
  pending: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onInterrupt: () => void;
  onMic: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "0px";
    node.style.height = `${Math.min(node.scrollHeight, 140)}px`;
  }, [value]);

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label className="sr" htmlFor="composer-input">
        {placeholder}
      </label>
      <textarea
        id="composer-input"
        data-testid="composer-input"
        ref={ref}
        lang={lang}
        rows={1}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      {interim ? (
        <p className="interim" data-testid="interim">
          {interim}
        </p>
      ) : null}
      <div className="composer-actions">
        <button
          type="button"
          className={listening ? "mic on" : "mic"}
          data-testid="mic-button"
          aria-pressed={listening}
          disabled={!sttReady}
          title={micLabel}
          onClick={onMic}
        >
          {listening ? "●" : "Mic"}
        </button>
        <button
          type="button"
          className="ghost"
          data-testid="interrupt-button"
          disabled={!pending}
          onClick={onInterrupt}
        >
          {interruptLabel}
        </button>
        <button type="submit" className="send" data-testid="send-button" disabled={!value.trim() || pending}>
          {sendLabel}
        </button>
      </div>
    </form>
  );
}
