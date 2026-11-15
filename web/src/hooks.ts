import { useCallback, useEffect, useRef, useState } from "react";
import type { Summary } from "./engine/summary";
import type { Knobs, Levers, Params } from "./engine/types";
import type { SimRequest } from "./engine/worker";

export function useSize<T extends HTMLElement>() {
  // a callback ref, so the observer attaches whenever the element mounts (also after a loading state)
  const ro = useRef<ResizeObserver | null>(null);
  const [width, setWidth] = useState(0);
  const ref = useCallback((el: T | null) => {
    ro.current?.disconnect();
    ro.current = null;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    ro.current = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.current.observe(el);
  }, []);
  useEffect(() => () => ro.current?.disconnect(), []);
  return [ref, width] as const;
}

type SimResult = { summary: Summary; ms: number };
type SimReply = { id: number } & (SimResult | { error: string } | { superseded: true });

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, { resolve: (r: SimResult | null) => void; reject: (e: Error) => void }>();
function failAll(msg: string) {
  for (const p of pending.values()) p.reject(new Error(msg));
  pending.clear();
}
function getWorker() {
  if (!worker) {
    worker = new Worker(new URL("./engine/worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (e: MessageEvent<SimReply>) => {
      const d = e.data;
      const p = pending.get(d.id);
      pending.delete(d.id);
      if (!p) return;
      if ("error" in d) p.reject(new Error(d.error));
      else p.resolve("superseded" in d ? null : d);
    };
    worker.onerror = (e) => failAll(`Simulation worker failed: ${e.message}`);
    worker.onmessageerror = () => failAll("Simulation worker sent an unreadable message");
  }
  return worker;
}

/** Resolves null when a newer request on the same lane replaced this one before it ran. */
function post(req: Omit<SimRequest, "id">) {
  return new Promise<SimResult | null>((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    getWorker().postMessage({ id, ...req } satisfies SimRequest);
  });
}

export function runSimulation(params: Params, knobs: Knobs, levers: Levers, nPaths = 5000, seed = 7) {
  return post({ params, knobs, levers, nPaths, seed }) as Promise<SimResult>;
}

/** Live Monte Carlo: re-runs (debounced, latest-wins) whenever inputs change. */
export function useSimulation(params: Params | null, knobs: Knobs, levers: Levers, nPaths = 5000) {
  const [state, setState] = useState<{ summary: Summary | null; ms: number; busy: boolean; error: string | null }>(
    { summary: null, ms: 0, busy: false, error: null });
  const latest = useRef(0);
  // each hook instance is its own lane, so the worker drops this hook's stale requests but not another hook's
  const [lane] = useState(() => nextId++);
  const key = JSON.stringify([params?.ticker, knobs, levers, nPaths]);
  useEffect(() => {
    if (!params) return;
    const ticket = ++latest.current;
    setState((s) => ({ ...s, busy: true }));
    const timer = setTimeout(() => {
      post({ params, knobs, levers, nPaths, seed: 7, lane }).then(
        (r) => { if (r && ticket === latest.current) setState({ summary: r.summary, ms: r.ms, busy: false, error: null }); },
        (e: Error) => { if (ticket === latest.current) setState((s) => ({ ...s, busy: false, error: e.message })); },
      );
    }, 60);
    return () => clearTimeout(timer);
    // `key` stands in for knobs/levers/nPaths, which callers often rebuild as new objects with the same content
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, params]);
  return state;
}

const safeDecode = (s: string) => {
  try { return decodeURIComponent(s); } catch { return s; }
};

export function useHashState(def: string): [string, (v: string) => void] {
  const [v, setV] = useState(() => safeDecode(location.hash.slice(1)) || def);
  useEffect(() => {
    const on = () => setV(safeDecode(location.hash.slice(1)) || def);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, [def]);
  return [v, (nv: string) => { location.hash = encodeURIComponent(nv); }];
}
