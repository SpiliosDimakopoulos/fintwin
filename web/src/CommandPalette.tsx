import { useEffect, useMemo, useRef, useState } from "react";
import type { Index } from "./data";
import { prettyName } from "./format";
import { Meter } from "./ui";

type Item = { ticker: string; name: string; sector: string; health: number; showcase: boolean };

export function CommandPalette({ index, open, onClose, onPick, liveEnabled }: {
  index: Index; open: boolean; onClose: () => void; onPick: (ticker: string) => void; liveEnabled: boolean;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const all: Item[] = useMemo(() => Object.entries(index.companies).map(([t, e]) => ({
    ticker: t, name: prettyName(e.name), sector: e.sector, health: e.matrix.base.health, showcase: e.showcase,
  })), [index]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) {
      const showcase = all.filter((i) => i.showcase).sort((a, b) => a.ticker.localeCompare(b.ticker));
      const rest = all.filter((i) => !i.showcase).sort((a, b) => a.ticker.localeCompare(b.ticker));
      return [{ group: "Featured", items: showcase }, { group: "All companies", items: rest }];
    }
    const scored = all.map((i) => {
      const t = i.ticker.toLowerCase(), n = i.name.toLowerCase(), sec = i.sector.toLowerCase();
      const score = t === s ? 0 : t.startsWith(s) ? 1 : n.startsWith(s) ? 2 : n.includes(s) ? 3 : sec.includes(s) ? 4 : 9;
      return { i, score };
    }).filter((x) => x.score < 9).sort((a, b) => a.score - b.score || a.i.ticker.localeCompare(b.i.ticker));
    return [{ group: `${scored.length} match${scored.length === 1 ? "" : "es"}`, items: scored.map((x) => x.i) }];
  }, [q, all]);
  const flat = results.flatMap((g) => g.items);
  const canLive = liveEnabled && /^[A-Za-z.\-]{1,6}$/.test(q.trim()) && !index.companies[q.trim().toUpperCase()];

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    setQ(""); setSel(0); setTimeout(() => inputRef.current?.focus(), 0);
    return () => opener?.focus();
  }, [open]);
  useEffect(() => setSel(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);
  if (!open) return null;

  const choose = (t: string) => { onPick(t); onClose(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") {
      if (flat[sel]) choose(flat[sel].ticker);
      else if (canLive) choose(q.trim().toUpperCase());
    }
  };

  let k = -1;
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette fade-in" role="dialog" aria-modal="true" aria-label="Find a company" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${all.length} companies by ticker, name or sector…`}
          aria-label="Search companies" role="combobox" aria-expanded aria-controls="palette-list" aria-autocomplete="list"
          aria-activedescendant={flat[sel] ? `palette-opt-${sel}` : undefined} />
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {results.map((g) => (
            <div key={g.group}>
              {g.items.length > 0 && <div className="palette-group" role="presentation">{g.group}</div>}
              {g.items.map((i) => {
                k++;
                const idx = k;
                return (
                  <div key={i.ticker} id={`palette-opt-${idx}`} data-i={idx} className="palette-item" role="option" aria-selected={idx === sel}
                    onMouseEnter={() => setSel(idx)} onClick={() => choose(i.ticker)}>
                    <span className="tk-cell">{i.ticker}</span>
                    <span className="p-name">{i.name} <span className="p-sector">· {i.sector}</span></span>
                    <span className="meter-cell" style={{ gridTemplateColumns: "1fr 26px", gap: 8 }}>
                      <Meter value={i.health} /><span className="num muted" style={{ textAlign: "right" }}>{i.health.toFixed(0)}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
          {flat.length === 0 && (
            <div style={{ padding: "18px 14px" }} className="muted">
              {canLive ? <>Press Enter to build a live twin for <b className="mono">{q.trim().toUpperCase()}</b> (needs the local API).</> : "No company matches."}
            </div>
          )}
        </div>
        <div className="palette-foot">
          <span><span className="kbd">↑</span> <span className="kbd">↓</span> navigate</span>
          <span><span className="kbd">↵</span> open</span>
          <span><span className="kbd">esc</span> close</span>
          <span style={{ marginLeft: "auto" }}>Bar = baseline health score</span>
        </div>
      </div>
    </div>
  );
}
