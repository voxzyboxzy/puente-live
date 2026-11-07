import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

const pack = {
  session: {
    id: "SES-TEST",
    phase: "intake",
    scenario_id: null,
    language: "en" as const,
    language_path: [] as string[],
    reported_polarities: {},
    error_codes: [] as string[],
    devices: [] as string[],
    phase_log: [],
    steps_done: [],
    steps_total: 0,
    current_step: null,
    failures: 0,
    technician: null,
    redaction_count: 0,
    resolution: null,
    ticket_id: null,
    llm_mode: "deterministic",
    provider: "deterministic",
  },
  assistant_text: "Puente Live is on the bridge.",
  transcript: [{ role: "assistant", text: "Puente Live is on the bridge.", language: "en" }],
  graph: {
    nodes: [
      {
        id: "report",
        status: "active",
        title_en: "Report",
        title_es: "Reporte",
        detail_en: "Waiting for the problem",
        detail_es: "Esperando el problema",
      },
    ],
    edges: [],
  },
  citations: [],
  ticket: null,
};

class MockSocket {
  static instance: MockSocket | null = null;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(public url: string) {
    MockSocket.instance = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
}

describe("App", () => {
  beforeEach(() => {
    MockSocket.instance = null;
    vi.stubGlobal("WebSocket", MockSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/sessions" && init?.method === "POST") {
          return json(pack);
        }
        if (url === "/api/scenarios") {
          return json({
            scenarios: [
              {
                id: "vpn_down",
                title_en: "Internet works, VPN does not",
                title_es: "El internet funciona, la VPN no",
                prompt_en: "My internet works but the VPN does not. Error code VPN-ERR-4012 on device ThinkPad-T14.",
                prompt_es: "El internet funciona pero la VPN no.",
              },
            ],
          });
        }
        if (url.includes("/messages")) {
          return json({
            ...pack,
            session: { ...pack.session, phase: "guide", language: "en", scenario_id: "vpn_down" },
            assistant_text: "The internet is working, and the VPN is not working.",
            transcript: [
              ...pack.transcript,
              { role: "user", text: "problem", language: "en" },
              { role: "assistant", text: "The internet is working, and the VPN is not working.", language: "en" },
            ],
          });
        }
        throw new Error(`unmocked ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the bridge and sends a scenario through the text fallback", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Puente")).toBeInTheDocument();
    expect(screen.getByTestId("llm-mode")).toHaveTextContent("deterministic");
    const scenario = await screen.findByTestId("scenario-vpn_down");
    await user.click(scenario);
    await waitFor(() => {
      expect(screen.getByTestId("transcript")).toHaveTextContent("VPN is not working");
    });
    expect(screen.getByTestId("node-report")).toBeInTheDocument();
  });
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
