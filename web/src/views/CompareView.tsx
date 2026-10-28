import { useMemo, useState } from "react";
import type { Index } from "../data";
import { pct } from "../format";
import { StripPlot } from "../charts/StripPlot";
import { useEffect } from "react";
import { loadBuildReport, type BuildReport } from "../data";
import { ModelNote, rowActions, Section } from "../ui";

type Metric = "health" | "p_breach";
type Mode = "level" | "change";

/** Quiet diverging tint around a neutral midpoint; the number in the cell carries the value. */
function tint(t: number) {
  const c = Math.max(-1, Math.min(1, t));
  const pole = c < 0 ? "var(--div-lo)" : "var(--div-hi)";
  return `color-mix(in oklab, ${pole} ${Math.round(Math.abs(c) * 46)}%, transparent)`;
}

export function CompareView({ index, onOpen }: { index: Index; onOpen: (t: string) => void }) {
  const presets = Object.entries(index.meta.presets);
  const [report, setReport] = useState<BuildReport | null>(null);
  useEffect(() => { loadBuildReport().then(setReport); }, []);
  const [sortKey, setSortKey] = useState("pandemic");
  const [desc, setDesc] = useState(false);
  const [metric, setMetric] = useState<Metric>("health");
  const [mode, setMode] = useState<Mode>("level");
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("all");
  const [view, setView] = useState<"table" | "dist">("dist");
  const groupOf = (e: { sector: string; gics?: string }) => e.gics || e.sector;
  const sectors = useMemo(() => [...new Set(Object.values(index.companies).map(groupOf))].filter(Boolean).sort(), [index]);

  const value = (t: string, k: string) => {
    const m = index.companies[t].matrix;
    const v = metric === "health" ? m[k].health : m[k].p_breach * 100;
    const b = metric === "health" ? m.base.health : m.base.p_breach * 100;
    return mode === "change" && k !== "base" ? v - b : v;
  };
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return Object.entries(index.companies)
      .filter(([t, e]) => (sector === "all" || groupOf(e) === sector) && (!s || t.toLowerCase().includes(s) || e.name.toLowerCase().includes(s)))
      .sort((a, b) => {
        const d = sortKey === "name" ? a[0].localeCompare(b[0]) : value(a[0], sortKey) - value(b[0], sortKey);
        return desc ? -d : d;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, sortKey, desc, q, sector, metric, mode]);

  const ariaSort = (k: string): "ascending" | "descending" | "none" => (k === sortKey ? (desc ? "descending" : "ascending") : "none");
  const sortBy = (k: string) => { if (k === sortKey) setDesc(!desc); else { setSortKey(k); setDesc(false); } };
  const cell = (t: string, k: string) => {
    const v = value(t, k);
    const isChange = mode === "change" && k !== "base";
    let bg: string, text: string;
    if (metric === "health") {
      bg = isChange ? tint(v / 50) : tint((v - 50) / 50);
      text = isChange ? (Math.round(v) === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(0)}`) : v.toFixed(0);
    } else {
      bg = isChange ? tint(-v / 50) : tint(-(v - 10) / 50);
      text = isChange ? (Math.abs(v) < 0.5 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(0)}`) : `${v.toFixed(0)}%`;
    }
    return { bg, text };
  };

  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">Matrix</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>{Object.keys(index.companies).length} companies, eight crises</h1>
        <p className="eyebrow" style={{ marginBottom: 8 }}>S&amp;P 500 outside financials and real estate, US-GAAP filers reporting in USD · rebuilt weekly</p>
        <p className="lede">Every cell is a full Monte Carlo run of 5,000 paths over 12 quarters on that company's own calibrated twin.
          Sort by any scenario to see who is most exposed to it.</p>
      </Section>

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", margin: "-6px 0 16px" }}>
        <div className="segmented" role="group" aria-label="View">
          <button aria-pressed={view === "dist"} onClick={() => setView("dist")}>Distribution</button>
          <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
        </div>
        <input type="search" placeholder="Filter by ticker or name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter companies" style={{ width: 220 }} />
        <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
          <option value="all">All sectors</option>
          {sectors.map((s) => <option key={s}>{s}</option>)}
        </select>
        <div className="segmented" role="group" aria-label="Metric">
          <button aria-pressed={metric === "health"} onClick={() => setMetric("health")}>Health score</button>
          <button aria-pressed={metric === "p_breach"} onClick={() => setMetric("p_breach")}>Runs out of cash</button>
        </div>
        {view === "table" && <div className="segmented" role="group" aria-label="Values">
          <button aria-pressed={mode === "level"} onClick={() => setMode("level")}>Level</button>
          <button aria-pressed={mode === "change"} onClick={() => setMode("change")}>Change vs baseline</button>
        </div>}
        <span className="muted" style={{ marginLeft: "auto" }}>{rows.length} shown</span>
      </div>

      {view === "dist" && (
        <div className="panel" style={{ padding: "20px 20px 12px" }}>
          <StripPlot rows={presets.map(([k, v]) => ({ key: k, label: v.label }))}
            items={rows.map(([t, e]) => ({ id: t, name: e.name, group: groupOf(e),
              values: Object.fromEntries(presets.map(([k]) => [k, metric === "health" ? e.matrix[k].health : e.matrix[k].p_breach * 100])) }))}
            focus={rows.length === 1 ? rows[0][0] : undefined} peers={sector !== "all" ? sector : undefined} onPick={onOpen} />
          <p className="muted" style={{ marginTop: 10 }}>{metric === "health" ? "Health score, 0–100" : "Probability of running out of cash, %"} · each dot is one company
            {sector !== "all" ? ` · ${sector} highlighted` : ""}. Filter by name to pin a company.</p>
        </div>
      )}
      {view === "table" && <><div className="table-wrap" style={{ maxHeight: "72vh", overflowY: "auto", border: "1px solid var(--rule)", borderRadius: 10, background: "var(--paper)" }}>
        <table style={{ borderCollapse: "separate", borderSpacing: 0 }}>
          <thead>
            <tr>
              <th aria-sort={ariaSort("name")} style={{ position: "sticky", top: 0, left: 0, zIndex: 3, background: "var(--paper)", paddingLeft: 14, minWidth: 220 }}>
                <button type="button" className="th-sort" onClick={() => sortBy("name")}>Company {sortKey === "name" ? (desc ? "↓" : "↑") : ""}</button>
              </th>
              {presets.map(([k, v]) => (
                <th key={k} className="r" aria-sort={ariaSort(k)} title={v.desc}
                  style={{ position: "sticky", top: 0, zIndex: 2, background: "var(--paper)", minWidth: 92, color: sortKey === k ? "var(--ink)" : undefined }}>
                  <button type="button" className="th-sort" onClick={() => sortBy(k)}>{v.label} {sortKey === k ? (desc ? "↓" : "↑") : ""}</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([t, e]) => (
              <tr key={t} className="clickable" aria-label={`Open ${t}`} {...rowActions(() => onOpen(t))}>
                <td style={{ position: "sticky", left: 0, background: "var(--paper)", zIndex: 1, paddingLeft: 14, whiteSpace: "nowrap" }}>
                  <span className="tk-cell" style={{ display: "inline-block", width: 52 }}>{t}</span>
                  <span className="muted" style={{ fontSize: 12 }}>{e.sector}</span>
                </td>
                {presets.map(([k]) => {
                  const { bg, text } = cell(t, k);
                  return (
                    <td key={k} className="r num" style={{ background: bg, borderBottom: "1px solid var(--paper)", borderLeft: "1px solid var(--paper)", padding: "7px 12px" }}
                      title={`${t} · ${index.meta.presets[k].label}: health ${e.matrix[k].health.toFixed(0)}, runs out of cash ${pct(e.matrix[k].p_breach, 1)}`}>
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend" style={{ marginTop: 12 }}>
        <span><span className="sw" style={{ background: tint(-1) }} />{metric === "health" ? "weaker" : "more likely to run out of cash"}</span>
        <span><span className="sw" style={{ background: "var(--wash)" }} />neutral</span>
        <span><span className="sw" style={{ background: tint(1) }} />{metric === "health" ? "stronger" : "safer"}</span>
        <span className="muted" style={{ marginLeft: "auto" }}>Leverage thresholds are only partly sector-adjusted, so regulated utilities can still read weaker than a credit analyst would rate them.</span>
      </div></>}
      <ModelNote />
      {report && Object.keys(report.failed).length > 0 && (
        <p className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>Not built this week: {Object.entries(report.failed).map(([t, why]) => `${t} (${why.split("\n")[0].slice(0, 80)})`).join("; ")}.</p>
      )}
    </div>
  );
}
