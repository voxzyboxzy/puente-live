import { useCallback, useEffect, useRef, useState } from "react";
import { speak, stopSpeaking, sttSupported, ttsSupported } from "./speech";
import type { BridgePack, Citation, Graph, Lang, ScenarioCard, Session, Ticket, ToolResult, Utterance } from "./types";

const EMPTY_GRAPH: Graph = { nodes: [], edges: [] };

type State = {
  session: Session | null;
  transcript: Utterance[];
  graph: Graph;
  citations: Citation[];
  tools: ToolResult[];
  ticket: Ticket | null;
  scenarios: ScenarioCard[];
  partial: string;
  pending: boolean;
  error: string | null;
  connected: boolean;
  chrome: Lang;
  follow: boolean;
  speechNote: string | null;
};

const initial: State = {
  session: null,
  transcript: [],
  graph: EMPTY_GRAPH,
  citations: [],
  tools: [],
  ticket: null,
  scenarios: [],
  partial: "",
  pending: false,
  error: null,
  connected: false,
  chrome: "en",
  follow: true,
  speechNote: null,
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function useBridge() {
  const [state, setState] = useState<State>(initial);
  const socketRef = useRef<WebSocket | null>(null);
  const waiters = useRef<Array<() => void>>([]);
  const sessionRef = useRef<Session | null>(null);

  const resolveWaiters = () => {
    const pending = waiters.current.splice(0);
    pending.forEach((fn) => fn());
  };

  const applyPack = useCallback((pack: BridgePack, replaceTranscript: boolean) => {
    sessionRef.current = pack.session;
    setState((current) => ({
      ...current,
      session: pack.session,
      graph: pack.graph || current.graph,
      citations: pack.citations || current.citations,
      tools: pack.tools || current.tools,
      ticket: pack.ticket ?? current.ticket,
      transcript: replaceTranscript && pack.transcript ? pack.transcript : current.transcript,
      chrome: current.follow ? pack.session.language : current.chrome,
      partial: "",
      pending: false,
      error: null,
    }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const socketHolder: { current: WebSocket | null } = { current: null };

    async function boot() {
      try {
        const [created, scenarioBody] = await Promise.all([
          fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language: "en" }),
          }).then((response) => readJson<BridgePack>(response)),
          fetch("/api/scenarios").then((response) => readJson<{ scenarios: ScenarioCard[] }>(response)),
        ]);
        if (cancelled) return;
        setState((current) => ({
          ...current,
          scenarios: scenarioBody.scenarios,
        }));
        applyPack(created, true);
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const socket = new WebSocket(`${protocol}://${window.location.host}/ws/sessions/${created.session.id}`);
        socketHolder.current = socket;
        socketRef.current = socket;
        socket.onopen = () => setState((current) => ({ ...current, connected: true }));
        socket.onclose = () => setState((current) => ({ ...current, connected: false }));
        socket.onerror = () => setState((current) => ({ ...current, connected: false }));
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data as string) as Record<string, unknown>;
          const type = String(message.type || "");
          if (type === "assistant_delta") {
            setState((current) => ({ ...current, partial: current.partial + String(message.text || "") }));
          } else if (type === "assistant_done") {
            const text = String(message.text || "");
            const language = (message.language as Lang) || sessionRef.current?.language || "en";
            setState((current) => ({
              ...current,
              partial: "",
              transcript: [...current.transcript, { role: "assistant", text, language }],
            }));
            if (ttsSupported()) speak(text, language);
            else setState((current) => ({ ...current, speechNote: "text-fallback" }));
          } else if (type === "interrupted") {
            stopSpeaking();
            const text = String(message.partial_text || "…");
            setState((current) => ({
              ...current,
              partial: "",
              pending: false,
              transcript: [...current.transcript, { role: "assistant", text, interrupted: true }],
            }));
          } else if (type === "graph") {
            setState((current) => ({ ...current, graph: message.graph as Graph }));
          } else if (type === "citations") {
            setState((current) => ({ ...current, citations: (message.citations as Citation[]) || [] }));
          } else if (type === "tools") {
            setState((current) => ({ ...current, tools: (message.tools as ToolResult[]) || [] }));
          } else if (type === "session") {
            const session = message.session as Session;
            sessionRef.current = session;
            setState((current) => {
              const transcript = current.transcript.slice();
              for (let index = transcript.length - 1; index >= 0; index -= 1) {
                if (transcript[index].role === "user") {
                  transcript[index] = { ...transcript[index], language: session.language };
                  break;
                }
              }
              return {
                ...current,
                session,
                transcript,
                chrome: current.follow ? session.language : current.chrome,
              };
            });
          } else if (type === "ticket") {
            setState((current) => ({ ...current, ticket: message.ticket as Ticket }));
          } else if (type === "turn_done") {
            setState((current) => ({ ...current, pending: false, partial: current.partial }));
            resolveWaiters();
          } else if (type === "error") {
            setState((current) => ({ ...current, error: String(message.message || "error"), pending: false }));
            resolveWaiters();
          }
        };
      } catch (error) {
        if (!cancelled) {
          setState((current) => ({
            ...current,
            error: error instanceof Error ? error.message : "Unable to open the bridge",
          }));
        }
      }
    }
    void boot();
    return () => {
      cancelled = true;
      socketHolder.current?.close();
    };
  }, [applyPack]);

  const sendText = useCallback(async (text: string, source = "text") => {
    const trimmed = text.trim();
    const session = sessionRef.current;
    if (!trimmed || !session) return;
    setState((current) => ({
      ...current,
      pending: true,
      partial: "",
      error: null,
      transcript: [...current.transcript, { role: "user", text: trimmed, language: current.session?.language }],
    }));
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      await new Promise<void>((resolve) => {
        waiters.current.push(resolve);
        socket.send(JSON.stringify({ type: "user_text", text: trimmed, source }));
      });
      return;
    }
    const pack = await readJson<BridgePack>(
      await fetch(`/api/sessions/${session.id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: trimmed, source }),
      }),
    );
    setState((current) => ({
      ...current,
      transcript: pack.transcript || current.transcript,
    }));
    applyPack(pack, false);
    if (pack.assistant_text) {
      if (ttsSupported()) speak(pack.assistant_text, pack.session.language);
      else setState((current) => ({ ...current, speechNote: "text-fallback" }));
    }
  }, [applyPack]);

  const interrupt = useCallback(() => {
    stopSpeaking();
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "interrupt" }));
    }
  }, []);

  const takeover = useCallback(async (techId: string, note: string) => {
    const session = sessionRef.current;
    if (!session) return;
    const pack = await readJson<BridgePack>(
      await fetch(`/api/sessions/${session.id}/takeover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tech_id: techId, note }),
      }),
    );
    applyPack(pack, true);
  }, [applyPack]);

  const technicianMessage = useCallback(async (text: string) => {
    const session = sessionRef.current;
    if (!session || !text.trim()) return;
    const pack = await readJson<BridgePack>(
      await fetch(`/api/sessions/${session.id}/technician`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    );
    applyPack(pack, true);
  }, [applyPack]);

  const download = useCallback(async (format: "json" | "markdown") => {
    const session = sessionRef.current;
    if (!session) return;
    const body = await readJson<{ content: unknown; ticket_id: string }>(
      await fetch(`/api/sessions/${session.id}/export?format=${format}`),
    );
    const content = format === "markdown" ? String(body.content) : JSON.stringify(body.content, null, 2);
    const blob = new Blob([content], { type: format === "markdown" ? "text/markdown" : "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${body.ticket_id || session.id}.${format === "markdown" ? "md" : "json"}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  const setChrome = (chrome: Lang) => setState((current) => ({ ...current, chrome, follow: false }));
  const setFollow = (follow: boolean) =>
    setState((current) => ({
      ...current,
      follow,
      chrome: follow && current.session ? current.session.language : current.chrome,
    }));

  return {
    ...state,
    sttReady: sttSupported(),
    ttsReady: ttsSupported(),
    sendText,
    interrupt,
    takeover,
    technicianMessage,
    download,
    setChrome,
    setFollow,
  };
}
