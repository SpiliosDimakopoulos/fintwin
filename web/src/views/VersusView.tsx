import { useEffect, useMemo, useState } from "react";
import { FanChart, FanLegend } from "../charts/FanChart";
import { loadCompany, type Company, type Index } from "../data";
import { RATINGS } from "../engine/ratings";
import type { Knobs } from "../engine/types";
import { fixed, futureQuarters, money, pct, prettyName } from "../format";
import { useSimulation } from "../hooks";
import { ModelNote, Section, Skeleton, Status } from "../ui";

const SCEN = ["base", "rates_200", "recession", "pandemic", "stagflation", "credit_crunch"] as const;

export function VersusView({ index, pair, onPair, onOpen }: {
  index: Index; pair: [string | undefined, string | undefined]; onPair: (a: string, b: string) => void; onOpen: (t: string) => void;
}) {
  const valid = (t?: string) => (t && index.companies[t.toUpperCase()] ? t.toUpperCase() : undefined);
  const [a, setA] = useState(valid(pair[0]) ?? "CCL");
  const [b, setB] = useState(valid(pair[1]) ?? "RCL");
  const [scen, setScen] = useState<string>("pandemic");
  const [ca, setCa] = useState<Company | null>(null);
  const [cb, setCb] = useState<Company | null>(null);
  useEffect(() => { onPair(a, b); setCa(null); loadCompany(a).then(setCa); }, [a]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onPair(a, b); setCb(null); loadCompany(b).then(setCb); }, [b]); // eslint-disable-line react-hooks/exhaustive-deps
  const knobs: Knobs = useMemo(() => ({ ...index.meta.presets[scen].knobs }), [scen, index]);
  const sa = useSimulation(ca?.params ?? null, knobs, index.meta.levers, 4000).summary;
  const sb = useSimulation(cb?.params ?? null, knobs, index.meta.levers, 4000).summary;
  const options = useMemo(() => Object.entries(index.companies).sort((x, y) => x[0].localeCompare(y[0])), [index]);

  const picker = (value: string, set: (t: string) => void, color: string, label: string) => (
    <label style={{ display: "grid", gap: 6 }}>
      <span className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="sw-line" style={{ background: color, width: 20 }} />{label}</span>
      <select value={value} onChange={(e) => set(e.target.value)} style={{ fontSize: 15, padding: "8px 10px" }} aria-label={label}>
        {options.map(([t, e]) => <option key={t} value={t}>{t} · {prettyName(e.name)}</option>)}
      </select>
    </label>
  );

  type Row = { label: string; fa: (c: Company) => number | null; show: (v: number) => string; better: "high" | "low"; sim?: boolean };
  const rows: Row[] = [
    { label: "Health score in this scenario", fa: (c) => (c === ca ? sa?.healthScore : sb?.healthScore) ?? null, show: (v) => v.toFixed(0), better: "high", sim: true },
    { label: "Runs out of cash", fa: (c) => (c === ca ? sa?.pBreach : sb?.pBreach) ?? null, show: (v) => pct(v, v > 0 && v < 0.1 ? 1 : 0), better: "low", sim: true },
    { label: "Junk at horizon", fa: (c) => (c === ca ? sa?.pSubIG : sb?.pSubIG) ?? null, show: (v) => pct(v), better: "low", sim: true },
    { label: "Health under baseline", fa: (c) => c.presets.base.health_score, show: (v) => v.toFixed(0), better: "high" },
    { label: "Breaking point (revenue drop)", fa: (c) => c.reverse_stress.sales_depth.p50 ?? 1, show: (v) => (v >= 1 ? "never" : `−${pct(v)}`), better: "high" },
    { label: "Cash and short-term investments", fa: (c) => c.params.cash0, show: (v) => money(v), better: "high" },
    { label: "Debt", fa: (c) => c.params.debt0, show: (v) => money(v), better: "low" },
    { label: "Fixed share of costs", fa: (c) => c.params.F / (c.params.F + c.params.v * (c.params.base_rev0 || 1)), show: (v) => pct(v), better: "low" },
    { label: "Debt maturing next 4 quarters", fa: (c) => c.params.maturities_q.slice(0, 4).reduce((x, y) => x + y, 0), show: (v) => money(v), better: "low" },
  ];
  const rating = (c: Company) => { const r = [...c.history.series.rating].reverse().find((x) => x != null); return r != null ? RATINGS[r] : "–"; };

  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">Compare</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>{a} versus {b}</h1>
        <p className="lede">Two twins, the same crisis, simulated side by side in your browser.</p>
      </Section>
      <div className="cols-2" style={{ marginTop: -8 }}>
        {picker(a, setA, "var(--s1)", "Company A")}
        {picker(b, setB, "var(--s2)", "Company B")}
      </div>
      <div className="chips" style={{ margin: "18px 0 6px" }}>
        {SCEN.map((k) => <button key={k} className="chip" aria-pressed={scen === k} onClick={() => setScen(k)}>{index.meta.presets[k].label}</button>)}
      </div>
      <p className="muted">{index.meta.presets[scen].desc}</p>

      {!ca || !cb ? <Skeleton h={420} /> : (
        <>
          <Section eyebrow="Head to head" title={scen === "base" ? "Under normal conditions" : `In a ${index.meta.presets[scen].label.toLowerCase()}`}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th></th>
                    <th className="r"><button className="btn-link" onClick={() => onOpen(a)}>{a}</button></th>
                    <th className="r"><button className="btn-link" onClick={() => onOpen(b)}>{b}</button></th></tr>
                </thead>
                <tbody>
                  <tr><td className="sub">Sector</td><td className="r">{ca.sector}</td><td className="r">{cb.sector}</td></tr>
                  <tr><td className="sub">Synthetic rating today</td><td className="r">{rating(ca)}</td><td className="r">{rating(cb)}</td></tr>
                  {rows.map((r) => {
                    const va = r.fa(ca), vb = r.fa(cb);
                    const win = va == null || vb == null || r.show(va) === r.show(vb) ? null : (r.better === "high" ? va > vb : va < vb) ? "a" : "b";
                    const cell = (v: number | null, me: "a" | "b") => (
                      <td className="r num" style={{ fontWeight: win === me ? 600 : 400 }}>
                        {v == null ? "…" : r.show(v)}{win === me && <span style={{ color: me === "a" ? "var(--s1)" : "var(--s2)", marginLeft: 6 }}>●</span>}
                      </td>
                    );
                    return <tr key={r.label}><td className="sub">{r.label}{r.sim && <span className="muted"> · live</span>}</td>{cell(va, "a")}{cell(vb, "b")}</tr>;
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ marginTop: 8 }}>● marks the stronger of the two on each line.</p>
          </Section>

          <Section eyebrow="Paths" title="Health score over the next three years">
            <FanLegend layers={[{ label: a, color: "var(--s1)" }, { label: b, color: "var(--s2)" }]} reported={false} />
            {!sa || !sb ? <Skeleton h={260} /> : (
              <div style={{ marginTop: 10 }}>
                <FanChart futureLabels={futureQuarters(ca.params.last_quarter, ca.params.horizon)} legend={false}
                  layers={[{ label: a, color: "var(--s1)", bands: sa.bands.health }, { label: b, color: "var(--s2)", bands: sb.bands.health }]}
                  yMin={0} yMax={100} format={(x) => x.toFixed(0)} tick={(x) => `${x}`} height={280} />
              </div>
            )}
            <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
              {sa && <span className="sub">{a}: <Status health={sa.healthScore} /> · breach {pct(sa.pBreach, 1)}</span>}
              {sb && <span className="sub">{b}: <Status health={sb.healthScore} /> · breach {pct(sb.pBreach, 1)}</span>}
              <span className="muted">Net debt/EBITDA tolerance: {fixed(ca.params.sector_tol ?? 1, 2)}× vs {fixed(cb.params.sector_tol ?? 1, 2)}× sector norm</span>
            </div>
            <ModelNote />
          </Section>
        </>
      )}
    </div>
  );
}
