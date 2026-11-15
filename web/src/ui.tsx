import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { healthStatus, MODEL_LIMIT_NOTE } from "./format";

/* ---------- motion ---------- */

/** Tween a number toward its new value (250 ms ease-out); respects reduced-motion. */
export function useTween(value: number, ms = 260) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    if (!Number.isFinite(value)) { setShown(value); return; }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(value); from.current = value; return; }
    const start = performance.now(), a = Number.isFinite(from.current) ? from.current : value;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / ms), e = 1 - (1 - k) ** 3;
      const v = a + (value - a) * e;
      setShown(v);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); from.current = value; };
  }, [value, ms]);
  return shown;
}

/** Row click as a mouse shortcut; the link inside the row is what keyboard and assistive-tech users follow. */
export function rowClick(fn: () => void) {
  return {
    onClick: (e: React.MouseEvent) => {
      if (!(e.target as HTMLElement).closest("a, button")) fn();
    },
  };
}

/* ---------- icons (1.5px strokes, 16px grid) ---------- */
const I = ({ d, size = 16 }: { d: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{d}</svg>
);
export const IconSun = () => <I d={<><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></>} />;
export const IconMoon = () => <I d={<path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z" />} />;
export const IconSearch = () => <I d={<><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></>} size={14} />;
export const IconArrow = () => <I d={<path d="M3 8h10M9 4l4 4-4 4" />} size={14} />;
export const IconChevron = () => <I d={<path d="m4.5 6.5 3.5 3.5 3.5-3.5" />} size={14} />;
export const IconExternal = () => <I d={<path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3" />} size={12} />;

export function Wordmark() {
  return (
    <span className="wordmark" aria-label="FinTwin">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="6" fill="var(--ink)" />
        <path d="M7 20.5c3-0.2 4.6-7 8-7s4.6 4.2 10 3.5" stroke="var(--page)" strokeWidth="2.6" fill="none" strokeLinecap="round" />
      </svg>
      <span className="wordmark-text">FinTwin</span>
    </span>
  );
}

/* ---------- building blocks ---------- */

export const REPO_URL = "https://github.com/SpiliosDimakopoulos/fintwin";
export const PAPER_URL = `${REPO_URL}/blob/main/docs/paper/fintwin.pdf`;

export function ExtLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return <a href={href} className={className} target="_blank" rel="noreferrer">{children}</a>;
}

/** Shown when a data file fails to load, instead of a skeleton that never resolves. */
export function LoadError({ what }: { what: string }) {
  return (
    <div className="callout" role="alert" style={{ margin: "12px 0 24px" }}>
      <p>Could not load {what}. Check your connection and reload the page.</p>
      <button className="btn" style={{ marginTop: 10 }} onClick={() => location.reload()}>Reload</button>
    </div>
  );
}

/** Opens on hover, keyboard focus or tap (iOS does not focus buttons on tap); Esc or a tap elsewhere closes it. */
export function InfoTip({ children }: { children: ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  return (
    <button ref={ref} type="button" className="info" aria-label="More information" aria-describedby={id}
      data-open={open && !dismissed ? "" : undefined} data-dismissed={dismissed ? "" : undefined}
      onClick={() => { setOpen(dismissed || !open); setDismissed(false); }}
      onBlur={() => { setOpen(false); setDismissed(false); }}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setDismissed(true); } }}>
      i<span className="pop" role="tooltip" id={id}>{children}</span>
    </button>
  );
}

export function Status({ health, label }: { health: number; label?: string }) {
  const s = healthStatus(health);
  return <span className="status"><i style={{ background: `var(--${s.key})` }} />{label ?? s.label}</span>;
}

/** One-line limit statement placed under model-implied risk numbers. */
export function ModelNote({ children }: { children?: ReactNode }) {
  return <p className="muted model-note" style={{ marginTop: 10, fontSize: 12.5, maxWidth: 820 }}>{children ?? MODEL_LIMIT_NOTE}</p>;
}

/** Says which specification and sample a block of dashboard numbers comes from. */
export function SpecStamp({ generated, children }: { generated?: string; children?: ReactNode }) {
  return (
    <p className="muted spec-stamp" style={{ fontSize: 12.5, maxWidth: 820, margin: "0 0 14px" }}>
      {children ?? <>Dashboard sample, run with the product specification{generated ? `, built ${generated}` : ""}. The paper reports a pre-specified and a revised
        specification on a separate research sample, so its figures differ from the ones on this page.</>}
    </p>
  );
}

export function Section({ eyebrow, title, note, right, children, id }: {
  eyebrow?: ReactNode; title?: ReactNode; note?: ReactNode; right?: ReactNode; children: ReactNode; id?: string;
}) {
  return (
    <section className="section" id={id}>
      {(eyebrow || title || right) && (
        <div className="section-head">
          <div className="left">
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && <h2 className="display h-m">{title}</h2>}
            {note && <p className="section-note">{note}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

type MetricProps = {
  label: ReactNode; value: number | null; format: (x: number) => string; unit?: string; foot?: ReactNode; info?: ReactNode;
};
export function Metric({ label, value, format, unit, foot, info }: MetricProps) {
  const v = useTween(value ?? NaN);
  return (
    <div className="metric">
      <div className="m-label">{label}{info && <InfoTip>{info}</InfoTip>}</div>
      <div className="m-value">{value == null || !Number.isFinite(v) ? "–" : format(v)}{unit && <span className="m-unit">{unit}</span>}</div>
      {foot && <div className="m-foot">{foot}</div>}
    </div>
  );
}

/** A metric whose value is text (rating, "survives"). */
export function MetricText({ label, value, foot, info }: { label: ReactNode; value: ReactNode; foot?: ReactNode; info?: ReactNode }) {
  return (
    <div className="metric">
      <div className="m-label">{label}{info && <InfoTip>{info}</InfoTip>}</div>
      <div className="m-value">{value}</div>
      {foot && <div className="m-foot">{foot}</div>}
    </div>
  );
}

/** Sign carried by word and arrow, colour only reinforces it. */
export function Delta({ value, fmt, goodIfPositive = true, suffix = "vs baseline" }: { value: number; fmt: (x: number) => string; goodIfPositive?: boolean; suffix?: string }) {
  if (!Number.isFinite(value) || Math.abs(value) < 1e-9) return <span>unchanged {suffix}</span>;
  const good = value > 0 === goodIfPositive;
  return <span className={good ? "delta-up" : "delta-down"}>{value > 0 ? "↑" : "↓"} {fmt(Math.abs(value))} {suffix}</span>;
}

/** 0-100 health scale with the four status zones, the median marker and the unlucky-decile range. */
export function HealthScale({ value, p10 }: { value: number; p10?: number }) {
  const zones = ["critical", "serious", "warning", "good"];
  return (
    <div className="hscale" role="img" aria-label={`Health score ${value.toFixed(0)} of 100`}>
      <div className="zone-labels"><span>High stress</span><span>Elevated</span><span>Moderate</span><span style={{ textAlign: "right" }}>Low stress</span></div>
      <div className="track">{zones.map((z) => <i key={z} style={{ background: `var(--${z})` }} />)}</div>
      {p10 != null && <div className="range" style={{ left: `${p10}%`, width: `${Math.max(value - p10, 0.5)}%` }} title="Unluckiest 10% of paths to median" />}
      <div className="marker" style={{ left: `${Math.min(Math.max(value, 0), 100)}%` }} />
      <div className="ticks">{[0, 30, 50, 70, 100].map((t) => <span key={t} style={{ left: `${t}%` }}>{t}</span>)}</div>
    </div>
  );
}

export function Meter({ value, max = 100, color }: { value: number; max?: number; color?: string }) {
  const s = healthStatus(value);
  return <div className="meter"><i style={{ width: `${Math.max(2, (value / max) * 100)}%`, background: color ?? `var(--${s.key})` }} /></div>;
}

export function Skeleton({ h = 200 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }} />;
}
