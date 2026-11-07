import { render, screen } from "@testing-library/react";
import { DiagnosticGraph } from "./DiagnosticGraph";
import type { Graph } from "../types";

const graph: Graph = {
  nodes: [
    {
      id: "check_vpn",
      status: "fail",
      title_en: "VPN",
      title_es: "VPN",
      detail_en: "Tunnel down · VPN-ERR-4012",
      detail_es: "Túnel caído · VPN-ERR-4012",
    },
    {
      id: "language",
      status: "info",
      title_en: "Language",
      title_es: "Idioma",
      detail_en: "ES · path en → es",
      detail_es: "ES · ruta en → es",
    },
  ],
  edges: [["language", "check_vpn"]],
};

describe("DiagnosticGraph", () => {
  it("renders check status and the active language", () => {
    render(<DiagnosticGraph graph={graph} lang="es" />);
    const vpn = screen.getByTestId("node-check_vpn");
    expect(vpn).toHaveAttribute("data-status", "fail");
    expect(vpn).toHaveTextContent("Túnel caído · VPN-ERR-4012");
    expect(screen.getByTestId("node-language")).toHaveTextContent("Idioma");
    expect(screen.getByTestId("node-language")).toHaveTextContent("en → es");
  });
});
