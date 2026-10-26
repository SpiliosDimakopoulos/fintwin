import { buildScenario } from "../engine/scenario";
import type { Knobs } from "../engine/types";
import { useSize } from "../hooks";

/** Thumbnail of the scenario being designed: the revenue path, plus bands for closed markets and spread shocks. */
export function ShockPreview({ knobs, T }: { knobs: Knobs; T: number }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const s = buildScenario(knobs, T);
  const H = 58, top = 6, bottom = 14;
  const w = Math.max(width, 120);
  const step = w / T;
  const y = (v: number) => top + (1 - v) * (H - top - bottom);
  const pts = Array.from(s.sales_shock).map((v, i) => `${(i + 0.5) * step},${y(1 + v)}`);
  const anyRate = s.rate_shift.some((v) => v !== 0), anySpread = s.spread_shift.some((v) => v !== 0);
  const shockParts = [s.refi_access.some((a) => a === 0) && "markets shut", anySpread && "spreads", anyRate && "rates"].filter(Boolean);
  const scenarioLabel = shockParts.length > 0 ? shockParts.join(", ") : "no markets-shut, spread, or rate shocks";
  return (
    <div ref={ref}>
      {width > 0 && (
        <svg width={w} height={H} role="img" aria-label={`Revenue shock preview; ${scenarioLabel}`} style={{ display: "block" }}>
          {Array.from(s.refi_access).map((a, i) => a === 0 && <rect key={`f${i}`} x={i * step} y={top} width={step - 1} height={H - top - bottom} fill="var(--s2)" opacity={0.12} />)}
          {Array.from(s.spread_shift).map((v, i) => v !== 0 && <rect key={`s${i}`} x={i * step} y={H - bottom - 3} width={step - 1} height={3} fill="var(--s2)" opacity={0.55} />)}
          <line x1={0} x2={w} y1={y(1)} y2={y(1)} stroke="var(--rule-2)" strokeDasharray="2 3" />
          <polygon points={`0,${y(1)} ${pts.join(" ")} ${w},${y(1)}`} fill="var(--s2)" opacity={0.14} />
          <polyline points={`0,${y(1)} ${pts.join(" ")}`} fill="none" stroke="var(--s2)" strokeWidth={1.75} strokeLinejoin="round" />
          <text x={0} y={H - 2} fontSize={9.5} fontFamily="var(--font-mono)" fill="var(--muted)">revenue vs plan</text>
          <text x={w} y={H - 2} fontSize={9.5} fontFamily="var(--font-mono)" fill="var(--muted)" textAnchor="end">
            {[s.refi_access.some((a) => a === 0) && "markets shut", anySpread && "spreads", anyRate && "rates"].filter(Boolean).join(" · ")}
          </text>
        </svg>
      )}
    </div>
  );
}
