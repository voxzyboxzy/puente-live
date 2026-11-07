import type { Lang } from "./types";

type RecognitionCtor = new () => SpeechRecognitionLike;

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  onspeechstart: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechResultEvent = {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
};

function recognitionCtor(): RecognitionCtor | null {
  const w = window as Window & {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function sttSupported(): boolean {
  return typeof window !== "undefined" && recognitionCtor() !== null;
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speak(text: string, lang: Lang): { ok: boolean; cancel: () => void } {
  if (!ttsSupported() || !text.trim()) {
    return { ok: false, cancel: () => undefined };
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang === "es" ? "es-ES" : "en-US";
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
  return {
    ok: true,
    cancel: () => window.speechSynthesis.cancel(),
  };
}

export function stopSpeaking(): void {
  if (ttsSupported()) window.speechSynthesis.cancel();
}

export function listen(options: {
  lang: Lang;
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onStart: () => void;
  onEnd: () => void;
  onError: (message: string) => void;
}): { stop: () => void } | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = options.lang === "es" ? "es-ES" : "en-US";
  rec.onresult = (event) => {
    let interim = "";
    let finalText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const piece = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += piece;
      else interim += piece;
    }
    if (interim) options.onInterim(interim);
    if (finalText.trim()) options.onFinal(finalText.trim());
  };
  rec.onspeechstart = () => options.onStart();
  rec.onerror = (event) => options.onError(event.error || "speech error");
  rec.onend = () => options.onEnd();
  rec.start();
  return {
    stop: () => {
      rec.onend = null;
      rec.stop();
    },
  };
}
