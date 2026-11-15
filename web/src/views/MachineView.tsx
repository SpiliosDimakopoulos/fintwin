import { useState } from "react";
import type { Company, Meta } from "../data";
import { RATINGS, ratingRank } from "../engine/ratings";
import { futureQuarters, money } from "../format";
import { useSimulation } from "../hooks";
import { Section } from "../ui";

type Box = { x: number; y: number; w: number; h: number };
const STOCKS: Record<string, Box & { label: string }> = {
  revenue: { x: 30, y: 60, w: 170, h: 70, label: "Revenue" },
  ebitda: { x: 30, y: 230, w: 170, h: 70, label: "Operating profit (EBITDA)" },
  cash: { x: 395, y: 220, w: 190, h: 90, label: "Cash (stock)" },
  debt: { x: 740, y: 220, w: 190, h: 90, label: "Debt (stock)" },
  ppe: { x: 395, y: 420, w: 190, h: 70, label: "Productive assets (PP&E)" },
};
const AUX = {
  rating: { x: 835, y: 85, r: 46, label: "Credit rating" },
  health: { x: 490, y: 80, r: 50, label: "Health score" },
};

function Flow({ d, width, color = "var(--s1)", label, lx, ly, anchor = "middle" }: {
  d: string; width: number; color?: string; label?: string; lx?: number; ly?: number; anchor?: "start" | "middle" | "end";
}) {
  // Pipe width carries magnitude; a thin animated dash on top shows direction of flow.
  return (
    <g>
      <path d={d} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" opacity={0.28} />
      <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeDasharray="6 8" markerEnd="url(#arrow)">
        <animate attributeName="stroke-dashoffset" from="28" to="0" dur="1.4s" repeatCount="indefinite" />
      </path>
      {label && <text x={lx} y={ly} textAnchor={anchor} fontSize={12} fill="var(--ink-2)">{label}</text>}
    </g>
  );
}

function Cloud({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <g>
      <path d={`M${x - 18},${y + 6} a9,9 0 0,1 4,-15 a11,11 0 0,1 20,-3 a9,9 0 0,1 14,10 a7,7 0 0,1 -4,8 z`}
        fill="var(--raised)" stroke="var(--rule-2)" strokeWidth={1.5} />
      <text x={x + 24} y={y + 3} fontSize={11} fill="var(--muted)">{label}</text>
    </g>
  );
}

function Path({ d }: { d: string }) {
  return <path d={d} fill="none" stroke="var(--rule-2)" strokeWidth={2} markerEnd="url(#arrow)" />;
}

function LoopTag({ x, y, id, kind }: { x: number; y: number; id: string; kind: "R" | "B" }) {
  return (
    <g>
      <circle cx={x} cy={y} r={15} fill="var(--raised)" stroke={kind === "R" ? "var(--s2)" : "var(--s3)"} strokeWidth={1.5} />
      <text x={x} y={y} dy="0.35em" textAnchor="middle" fontSize={12} fontWeight={700} fill="var(--ink)">{id}</text>
    </g>
  );
}

export function MachineView({ c, meta }: { c: Company; meta: Meta }) {
  const [preset, setPreset] = useState("base");
  const [q, setQ] = useState(3);
  const sim = useSimulation(c.params, meta.presets[preset].knobs, meta.levers, 2000);
  const fut = futureQuarters(c.params.last_quarter, c.params.horizon);
  const s = sim.summary;
  const med = (k: "revenue" | "ebitda" | "cash" | "debt" | "interest" | "icr" | "health" | "fcf") => s ? s.bands[k][2][q] : 0;
  const rev = med("revenue");
  const scale = (v: number) => Math.max(2, Math.min(22, (Math.abs(v) / Math.max(rev, 1)) * 40));
  const icr = med("icr");
  const ratingIdx = Math.max(ratingRank(icr), 0);

  const valueText = (key: keyof typeof STOCKS) => {
    const map: Record<string, number> = { revenue: rev, ebitda: med("ebitda"), cash: med("cash"), debt: med("debt"), ppe: NaN };
    return Number.isFinite(map[key]) ? money(map[key]) : "";
  };

  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">{c.ticker} · mechanics</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>The machine inside the company</h1>
        <p className="lede">Stocks accumulate and flows fill or drain them. Four feedback loops decide whether a shock fades
          or spirals: two that amplify it, and two that represent management fighting back.</p>
      </Section>
      <div style={{ display: "flex", gap: 24, alignItems: "end", flexWrap: "wrap", justifyContent: "space-between", marginBottom: 12 }}>
        <div className="chips">
          {Object.entries(meta.presets).map(([k, v]) => (
            <button key={k} className="chip" aria-pressed={preset === k} onClick={() => setPreset(k)}>{v.label}</button>
          ))}
        </div>
        <label className="slider" style={{ width: 320, padding: 0 }}>
          <span className="slider-top"><span>Quarter shown (median path)</span><b>{fut[q]}</b></span>
          <input type="range" min={0} max={fut.length - 1} value={q} onChange={(e) => setQ(+e.target.value)} />
        </label>
      </div>
      <div className="panel" style={{ padding: "8px 8px 0" }}>
        <div style={{ width: "100%", overflowX: "auto" }} tabIndex={0} role="region" aria-label="Stock and flow diagram, scrollable">
          <svg viewBox="0 0 960 540" style={{ width: "100%", minWidth: 640, height: "auto" }} role="img"
            aria-label="Stock and flow diagram of the company's financial dynamics">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="var(--ink-2)" />
              </marker>
            </defs>

            {/* sources and sinks (clouds, in stock-and-flow notation) */}
            <Cloud x={115} y={20} label="customers" />
            <Cloud x={700} y={140} label="lenders" />
            <Cloud x={200} y={470} label="shareholders" />
            {/* operating flows */}
            <Path d="M115,34 L115,56" />
            <Flow d="M115,130 L115,226" width={scale(rev)} label="− operating costs" lx={130} ly={176} anchor="start" />
            <text x={130} y={192} fontSize={11} fill="var(--muted)">fixed + variable</text>
            <Flow d="M200,265 L390,265" width={scale(med("ebitda"))} label="operating cash flow" lx={295} ly={250} />
            <Flow d="M520,310 L520,416" width={scale(rev * c.params.capex_ratio)} label="capex" lx={532} ly={368} anchor="start" />
            <Flow d="M460,416 L460,314" width={3} color="var(--s3)" label="D&A" lx={448} ly={368} anchor="end" />
            {/* financing flows */}
            <Flow d="M736,248 L590,248" width={scale(Math.max(c.params.maturities_q[q] ?? 0, 1))} label="new debt & refinancing" lx={662} ly={238} />
            <Flow d="M590,286 L736,286" width={scale(c.params.maturities_q[q] ?? 0)} color="var(--s2)" label="maturities repaid" lx={662} ly={306} />
            <Flow d="M480,218 C480,170 600,150 672,145" width={scale(med("interest"))} color="var(--s2)" label="interest" lx={560} ly={150} />
            <Flow d="M405,312 C380,380 300,440 228,462" width={3} color="var(--s2)" label="dividends & buybacks" lx={318} ly={415} anchor="end" />
            {/* information links (dashed): what each decision reads */}
            <path d="M835,131 C835,170 845,190 840,216" fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="4 4" markerEnd="url(#arrow)" />
            <path d="M200,95 L436,85" fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="4 4" markerEnd="url(#arrow)" />
            <path d="M585,232 C660,140 740,70 789,78" fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="4 4" markerEnd="url(#arrow)" />
            {Object.entries(STOCKS).map(([k, b]) => (
              <g key={k}>
                <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={10} fill="var(--raised)" stroke="var(--rule-2)" strokeWidth={1.5} />
                <text x={b.x + b.w / 2} y={b.y + 26} textAnchor="middle" fontSize={13} fill="var(--ink-2)">{b.label}</text>
                <text x={b.x + b.w / 2} y={b.y + 52} textAnchor="middle" fontSize={22} fontWeight={500} fill="var(--ink)" fontFamily="var(--font-display)">{valueText(k as keyof typeof STOCKS)}</text>
              </g>
            ))}
            <g>
              <circle cx={AUX.rating.x} cy={AUX.rating.y} r={AUX.rating.r} fill="var(--raised)" stroke="var(--rule-2)" strokeWidth={1.5} />
              <text x={AUX.rating.x} y={AUX.rating.y - 6} textAnchor="middle" fontSize={11} fill="var(--ink-2)">{AUX.rating.label}</text>
              <text x={AUX.rating.x} y={AUX.rating.y + 16} textAnchor="middle" fontSize={22} fontWeight={500} fill="var(--ink)" fontFamily="var(--font-display)">{s ? RATINGS[ratingIdx] : ""}</text>
            </g>
            <g>
              <circle cx={AUX.health.x} cy={AUX.health.y} r={AUX.health.r} fill="var(--raised)" stroke="var(--ink)" strokeWidth={1.5} />
              <text x={AUX.health.x} y={AUX.health.y - 8} textAnchor="middle" fontSize={11} fill="var(--ink-2)">{AUX.health.label}</text>
              <text x={AUX.health.x} y={AUX.health.y + 18} textAnchor="middle" fontSize={28} fontWeight={500} fill="var(--ink)" fontFamily="var(--font-display)">{s ? med("health").toFixed(0) : ""}</text>
            </g>
            <text x={852} y={190} fontSize={11} fill="var(--muted)">rating → spread</text>
            <text x={490} y={472} textAnchor="middle" fontSize={11} fill="var(--muted)">capex in · depreciation out</text>

            <LoopTag x={690} y={190} id="R1" kind="R" />
            <LoopTag x={790} y={340} id="R2" kind="R" />
            <LoopTag x={300} y={370} id="B1" kind="B" />
            <LoopTag x={60} y={185} id="B2" kind="B" />
          </svg>
        </div>
      </div>

      <p className="muted only-phone" style={{ marginTop: 6 }}>Swipe sideways to see the whole diagram.</p>
      {s && (
        <div className="table-wrap" style={{ marginTop: 14 }}>
          <table aria-label={`Median values in ${fut[q]}`}>
            <thead><tr><th>{fut[q]}, median path</th>{(["revenue", "ebitda", "cash", "debt"] as const).map((k) => <th key={k} className="r">{STOCKS[k].label}</th>)}<th className="r">Credit rating</th><th className="r">Health score</th></tr></thead>
            <tbody><tr><td className="sub">{meta.presets[preset].label}</td>
              {(["revenue", "ebitda", "cash", "debt"] as const).map((k) => <td key={k} className="r num">{valueText(k)}</td>)}
              <td className="r">{RATINGS[ratingIdx]}</td><td className="r num">{med("health").toFixed(0)}</td></tr></tbody>
          </table>
        </div>
      )}

      <Section eyebrow="Feedback loops" title="Why shocks fade or spiral">
        <div className="cols-2" style={{ rowGap: 28 }}>
          {[
            ["R1", "Leverage–spread spiral", "Weaker earnings cut interest coverage, so the synthetic rating falls. New and refinanced debt carries a wider spread, interest rises, cash drains and more borrowing is needed.", "var(--s2)"],
            ["R2", "Market-access cliff", "Below 1.5× coverage only 60% of a funding need can be placed, and below 0.8× only 30%. Maturities are then paid from cash, which pushes coverage lower still.", "var(--s2)"],
            ["B1", "Cash conservation", "When cash nears its floor or coverage drops under 2.5×, dividends and buybacks stop and capital spending falls to maintenance.", "var(--s3)"],
            ["B2", "Delayed restructuring", "After two quarters of squeezed margins, fixed costs fall 4% a quarter, to a floor of 15% below normal, and recover when margins do.", "var(--s3)"],
          ].map(([id, t, d, col]) => (
            <div key={id} style={{ display: "grid", gridTemplateColumns: "40px 1fr", gap: 6 }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 500, color: col }}>{id}</span>
              <div><h3 className="display h-s" style={{ marginBottom: 6 }}>{t}</h3><p className="sub" style={{ fontSize: 13.5 }}>{d}</p></div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
