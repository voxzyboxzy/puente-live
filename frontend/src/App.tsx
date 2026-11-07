import { useState } from "react";
import { Composer } from "./components/Composer";
import { DiagnosticGraph } from "./components/DiagnosticGraph";
import { t } from "./i18n";
import { listen, sttSupported } from "./speech";
import { useBridge } from "./useBridge";

const PHASES = ["intake", "diagnose", "plan", "guide", "verify", "resolved", "handoff", "technician"];

export function App() {
  const bridge = useBridge();
  const lang = bridge.chrome;
  const strings = t(lang);
  const [draft, setDraft] = useState("");
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [handle, setHandle] = useState<{ stop: () => void } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [techId, setTechId] = useState("tech-synthetic-01");
  const [techNote, setTechNote] = useState("");
  const [asTech, setAsTech] = useState(false);

  const phase = bridge.session?.phase || "intake";
  const taken = phase === "technician";

  async function send(text: string, source = "text") {
    setDraft("");
    setInterim("");
    await bridge.sendText(text, source);
  }

  function toggleMic() {
    if (handle) {
      handle.stop();
      setHandle(null);
      setListening(false);
      return;
    }
    const next = listen({
      lang: bridge.session?.language || lang,
      onInterim: setInterim,
      onFinal: (text) => {
        setInterim("");
        void send(text, "browser_stt");
      },
      onStart: () => {
        if (bridge.pending) bridge.interrupt();
      },
      onEnd: () => setListening(false),
      onError: () => setListening(false),
    });
    if (!next) return;
    setHandle(next);
    setListening(true);
  }

  async function playDemo() {
    setPlaying(true);
    try {
      const replay = await fetch("/api/replays/vpn_switch").then((response) => response.json());
      for (const turn of replay.turns as string[]) {
        await send(turn, "replay");
      }
    } finally {
      setPlaying(false);
    }
  }

  async function submit() {
    if (asTech || taken && asTech) {
      await bridge.technicianMessage(draft);
      setDraft("");
      return;
    }
    await send(draft);
  }

  return (
    <div className="shell" data-testid="app-shell" data-phase={phase}>
      <header className="topbar">
        <div className="brand">
          <span className="arch" aria-hidden="true" />
          <div>
            <strong>Puente</strong>
            <em>Live</em>
          </div>
        </div>
        <p className="tag">English ↔ Spanish incident bridge</p>
        <div className="top-meta">
          <span className={bridge.connected ? "pill live" : "pill"}>{bridge.connected ? strings.live : "REST"}</span>
          <span className="pill">{strings.simulated}</span>
          <span className="pill mono" data-testid="llm-mode">
            {bridge.session?.llm_mode || "deterministic"}
          </span>
          <span className="pill mono" data-testid="language-badge">
            {(bridge.session?.language || "en").toUpperCase()}
            {bridge.session?.language_path?.length ? ` · ${bridge.session.language_path.join("→")}` : ""}
          </span>
          <div className="lang-toggle" role="group" aria-label="Chrome language">
            <button type="button" className={lang === "en" ? "on" : ""} onClick={() => bridge.setChrome("en")}>
              EN
            </button>
            <button type="button" className={lang === "es" ? "on" : ""} onClick={() => bridge.setChrome("es")}>
              ES
            </button>
          </div>
          <label className="follow">
            <input
              type="checkbox"
              checked={bridge.follow}
              onChange={(event) => bridge.setFollow(event.target.checked)}
            />
            {strings.follow}
          </label>
        </div>
      </header>

      <main className="workspace">
        <section className="conversation" aria-live="polite">
          <div className="thread" data-testid="transcript">
            {bridge.transcript.map((turn, index) => (
              <article key={`${turn.role}-${index}`} className={`bubble role-${turn.role}`}>
                <header>
                  <span>{turn.role}</span>
                  {turn.language ? <span className="mono">{turn.language}</span> : null}
                  {turn.interrupted ? <span className="flag">interrupted</span> : null}
                  {turn.redaction_count ? (
                    <span className="flag">{turn.redaction_count} {strings.redactions}</span>
                  ) : null}
                </header>
                <p>{turn.text}</p>
              </article>
            ))}
            {bridge.partial ? (
              <article className="bubble role-assistant live">
                <header>
                  <span>assistant</span>
                  <span className="flag">speaking</span>
                </header>
                <p>{bridge.partial}</p>
              </article>
            ) : null}
            {bridge.transcript.length <= 1 && !bridge.pending ? (
              <div className="empty">
                <p>{strings.emptyLead}</p>
                <h2>{strings.scenarios}</h2>
                <div className="cards">
                  {bridge.scenarios.map((scenario) => (
                    <button
                      key={scenario.id}
                      type="button"
                      className="scenario"
                      data-testid={`scenario-${scenario.id}`}
                      onClick={() => void send(lang === "es" ? scenario.prompt_es : scenario.prompt_en)}
                    >
                      <strong>{lang === "es" ? scenario.title_es : scenario.title_en}</strong>
                      <span>{lang === "es" ? scenario.prompt_es : scenario.prompt_en}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          {bridge.speechNote || !bridge.ttsReady ? <p className="speech-note">{strings.speakOff}</p> : null}
          {!sttSupported() ? <p className="speech-note">{strings.micOff}</p> : null}
          {bridge.error ? <p className="error-note">{bridge.error}</p> : null}
          <div className="replay-row">
            <button type="button" data-testid="replay-button" onClick={() => void playDemo()} disabled={playing || bridge.pending}>
              {playing ? strings.playing : strings.play}
            </button>
            {taken ? (
              <label className="follow">
                <input type="checkbox" checked={asTech} onChange={(event) => setAsTech(event.target.checked)} />
                {strings.asTech}
              </label>
            ) : null}
          </div>
          <Composer
            lang={lang}
            value={draft}
            interim={interim}
            placeholder={strings.placeholder}
            sendLabel={strings.send}
            interruptLabel={strings.interrupt}
            micLabel={listening ? strings.micOn : strings.mic}
            listening={listening}
            sttReady={bridge.sttReady}
            pending={bridge.pending}
            onChange={setDraft}
            onSend={() => void submit()}
            onInterrupt={bridge.interrupt}
            onMic={toggleMic}
          />
        </section>

        <aside className="side">
          <div className="side-head">
            <h2>{strings.graph}</h2>
            <p className="hint">{strings.facts}</p>
          </div>
          <div className="phases" data-testid="phase-breadcrumb" aria-label={strings.phases}>
            {PHASES.map((item) => (
              <span key={item} className={item === phase ? "phase on" : "phase"}>
                {item}
              </span>
            ))}
          </div>
          <DiagnosticGraph graph={bridge.graph} lang={lang} />
          <section className="cite-block">
            <h3>{strings.citations}</h3>
            {bridge.citations.length === 0 ? <p className="hint">{strings.noCite}</p> : null}
            {bridge.citations.map((item) => (
              <article key={item.id} className="cite" data-testid={`cite-${item.id}`}>
                <header>
                  <span className="mono">{item.source_label}</span>
                  <span className="mono">overlap {item.overlap}</span>
                </header>
                <strong>{item.title}</strong>
                <p>{item.excerpt}</p>
              </article>
            ))}
          </section>
          <section className="ticket-block" data-testid="ticket-panel">
            <h3>{strings.ticket}</h3>
            {bridge.ticket ? (
              <div className="ticket-grid">
                <span className="mono" data-testid="ticket-status">
                  {bridge.ticket.ticket_id} · {bridge.ticket.status}
                </span>
                <span>{(bridge.ticket.error_codes || bridge.session?.error_codes || []).join(", ") || "—"}</span>
                <span>{(bridge.ticket.devices || bridge.session?.devices || []).join(", ") || "—"}</span>
                <span className="mono">
                  {Object.entries(bridge.ticket.reported_polarities || bridge.session?.reported_polarities || {})
                    .map(([key, value]) => `${key}=${value}`)
                    .join(" · ") || "—"}
                </span>
              </div>
            ) : (
              <p className="hint">—</p>
            )}
            <div className="ticket-actions">
              <button type="button" data-testid="ticket-json" onClick={() => void bridge.download("json")}>
                {strings.downloadJson}
              </button>
              <button type="button" data-testid="ticket-md" onClick={() => void bridge.download("markdown")}>
                {strings.downloadMd}
              </button>
            </div>
            <form
              className="takeover"
              onSubmit={(event) => {
                event.preventDefault();
                void bridge.takeover(techId, techNote);
              }}
            >
              <h3>{taken ? strings.taken : strings.takeover}</h3>
              <label>
                {strings.techId}
                <input value={techId} onChange={(event) => setTechId(event.target.value)} />
              </label>
              <label>
                {strings.techNote}
                <input
                  value={techNote}
                  onChange={(event) => setTechNote(event.target.value)}
                  placeholder="synthetic note"
                />
              </label>
              <button type="submit" data-testid="takeover-button">
                {strings.take}
              </button>
            </form>
          </section>
        </aside>
      </main>
    </div>
  );
}
