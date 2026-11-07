import type { Graph, Lang } from "../types";

const POS: Record<string, [number, number]> = {
  report: [8, 8],
  language: [198, 8],
  entities: [388, 8],
  hypothesis: [128, 96],
  check_wifi: [8, 188],
  check_vpn: [122, 188],
  check_dns: [236, 188],
  check_printer: [350, 188],
  reset_password: [464, 188],
  kb: [8, 300],
  plan: [198, 300],
  verify: [388, 300],
  ticket: [168, 404],
};

const WIDTH: Record<string, number> = {
  report: 176,
  language: 176,
  entities: 176,
  hypothesis: 320,
  check_wifi: 108,
  check_vpn: 108,
  check_dns: 108,
  check_printer: 108,
  reset_password: 108,
  kb: 176,
  plan: 176,
  verify: 176,
  ticket: 250,
};

export function DiagnosticGraph({ graph, lang }: { graph: Graph; lang: Lang }) {
  const nodes = graph.nodes || [];
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  return (
    <div className="graph-wrap" data-testid="graph">
      <svg className="graph-edges" viewBox="0 0 580 470" aria-hidden="true">
        {(graph.edges || []).map(([from, to]) => {
          const a = POS[from];
          const b = POS[to];
          if (!a || !b) return null;
          return (
            <line
              key={`${from}-${to}`}
              x1={a[0] + (WIDTH[from] || 108) / 2}
              y1={a[1] + 30}
              x2={b[0] + (WIDTH[to] || 108) / 2}
              y2={b[1] + 16}
            />
          );
        })}
      </svg>
      <div className="graph-stage">
        {Object.entries(POS).map(([id, [x, y]]) => {
          const node = byId[id];
          if (!node) return null;
          const title = lang === "es" ? node.title_es : node.title_en;
          const detail = lang === "es" ? node.detail_es : node.detail_en;
          return (
            <article
              key={id}
              className={`gnode status-${node.status}`}
              style={{ left: x, top: y, width: WIDTH[id] || 108 }}
              data-testid={`node-${id}`}
              data-status={node.status}
            >
              <header>{title}</header>
              <p>{detail}</p>
            </article>
          );
        })}
      </div>
    </div>
  );
}
