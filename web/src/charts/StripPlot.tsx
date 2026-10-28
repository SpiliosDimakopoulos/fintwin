import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { prettyName } from "../format";
import { useSize } from "../hooks";

export type StripRow = { key: string; label: string };
export type StripItem = { id: string; name: string; group: string; values: Record<string, number> };

/**
 * One row per scenario, one dot per company. Hovering a company joins its dots across rows, so you can
 * follow a single name through every crisis. `focus` pins one company; `peers` tints a group (its sector).
 */
export function StripPlot({ rows, items, focus, peers, onPick, height: rowH = 46, compact = false }: {
  rows: StripRow[]; items: StripItem[]; focus?: string; peers?: string; onPick?: (id: string) => void; height?: number; compact?: boolean;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const labelW = compact ? 92 : Math.min(150, Math.max(width * 0.2, 96));
  const M = { t: compact ? 4 : 20, r: 16, b: 22 };
  const H = M.t + rows.length * rowH + M.b;
  const x = scaleLinear().domain([0, 100]).range([labelW, Math.max(width - M.r, labelW + 100)]);
  const yRow = (i: number) => M.t + i * rowH + rowH / 2;
  // deterministic vertical jitter so overlapping dots stay visible
  const jitter = (id: string) => {
    let h = 0;
    for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 997;
    return ((h / 997) - 0.5) * (rowH * 0.5);
  };
  const active = hover ?? focus;
  // keyboard: one tab stop; arrows walk companies in order of their first-row score, Enter opens
  const order = [...items].sort((a, b) => (a.values[rows[0]?.key] ?? 0) - (b.values[rows[0]?.key] ?? 0)).map((i) => i.id);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && active && onPick) { e.preventDefault(); onPick(active); return; }
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step || !order.length) return;
    e.preventDefault();
    const i = active ? order.indexOf(active) : -1;
    setHover(order[(i + step + order.length) % order.length]);
  };
  const activeItem = items.find((i) => i.id === active);

  return (
    <div className="chart" ref={ref} onPointerLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={H} role="group" aria-label={`Health score by company across ${rows.map((r) => r.label).join(", ")}: ${items.length} companies. Focus the chart and use the arrow keys to walk through companies${onPick ? "; Enter opens one" : ""}.`}
          tabIndex={0} onKeyDown={onKey} onBlur={() => setHover(null)}>
          {[0, 30, 50, 70, 100].map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={M.t} y2={H - M.b} stroke="var(--rule)" strokeDasharray={t === 0 || t === 100 ? undefined : "2 3"} />
              <text className="tick" x={x(t)} y={H - 6} textAnchor="middle">{t}</text>
            </g>
          ))}
          {rows.map((r, i) => (
            <g key={r.key}>
              {i > 0 && <line x1={0} x2={width - M.r} y1={M.t + i * rowH} y2={M.t + i * rowH} stroke="var(--rule)" />}
              <text x={0} y={yRow(i)} dy="0.32em" fontSize={12.5} fill="var(--ink-2)">{r.label}</text>
            </g>
          ))}
          {rows.map((r, i) => items.map((it) => {
            const v = it.values[r.key];
            if (v == null) return null;
            const isPeer = peers && it.group === peers;
            return (
              <circle key={`${r.key}-${it.id}`} cx={x(v)} cy={yRow(i) + jitter(it.id)} r={isPeer ? 4 : 3.2}
                fill={isPeer ? "var(--s1)" : "var(--ink-2)"} opacity={active && active !== it.id ? (isPeer ? 0.55 : 0.18) : isPeer ? 0.85 : 0.38}
                style={{ cursor: onPick ? "pointer" : undefined, transition: "opacity 0.15s" }}
                onPointerEnter={() => setHover(it.id)} onClick={() => onPick?.(it.id)} />
            );
          }))}
          {activeItem && (
            <g pointerEvents="none">
              <polyline fill="none" stroke="var(--s2)" strokeWidth={1.5} strokeLinejoin="round"
                points={rows.map((r, i) => `${x(activeItem.values[r.key])},${yRow(i) + jitter(activeItem.id)}`).join(" ")} />
              {rows.map((r, i) => (
                <g key={r.key}>
                  <circle cx={x(activeItem.values[r.key])} cy={yRow(i) + jitter(activeItem.id)} r={5.5} fill="var(--s2)" stroke="var(--page)" strokeWidth={2} />
                  {(!compact || i === 0) && (
                    <text x={x(activeItem.values[r.key]) + (activeItem.values[r.key] > 85 ? -10 : 10)} y={yRow(i) + jitter(activeItem.id) - 8}
                      textAnchor={activeItem.values[r.key] > 85 ? "end" : "start"} fontSize={11} fontFamily="var(--font-mono)" fill="var(--ink)">
                      {i === 0 ? `${activeItem.id} ${activeItem.values[r.key].toFixed(0)}` : activeItem.values[r.key].toFixed(0)}
                    </text>
                  )}
                </g>
              ))}
            </g>
          )}
        </svg>
      )}
      {!compact && (
        <div className="muted" style={{ minHeight: 18, marginTop: 4 }}>
          {activeItem ? <><b aria-live="polite" className="mono" style={{ color: "var(--ink)" }}>{activeItem.id}</b> {prettyName(activeItem.name)} · {activeItem.group}{onPick ? " · click to open" : ""}</> : "Hover a dot to follow one company through every scenario."}
        </div>
      )}
    </div>
  );
}
