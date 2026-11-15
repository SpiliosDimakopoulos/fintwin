import { clampScenario, type KnobKey } from "./ask/parse";
import type { Meta } from "./data";
import { KNOB_DEFAULTS } from "./engine/scenario";
import type { Knobs, Levers } from "./engine/types";

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/** Scenario state <-> URL query: only what differs from the preset (knobs) or the defaults (levers). */
export function decode(query: string, meta: Meta, preset: string): { knobs: Knobs; levers: Levers } {
  const q = new URLSearchParams(query);
  const raw: Partial<Record<KnobKey, number>> = {};
  for (const pair of (q.get("k") ?? "").split(";").filter(Boolean)) {
    const [name, v] = pair.split(":");
    // own keys only ("constructor", "toString" are `in` every object); values are clamped like the Ask path
    if (own(KNOB_DEFAULTS, name) && v !== undefined && v.trim() !== "" && Number.isFinite(+v)) raw[name as KnobKey] = +v;
  }
  const knobs: Knobs = { ...(meta.presets[preset]?.knobs ?? {}), ...clampScenario({ knobs: raw, levers: {} }).knobs };
  const levers = { ...meta.levers };
  for (const name of (q.get("off") ?? "").split(",").filter(Boolean)) if (own(levers, name)) levers[name as keyof Levers] = false;
  for (const name of (q.get("on") ?? "").split(",").filter(Boolean)) if (own(levers, name)) levers[name as keyof Levers] = true;
  return { knobs, levers };
}
export function encode(knobs: Knobs, levers: Levers, meta: Meta, preset: string): string {
  const ref = { ...KNOB_DEFAULTS, ...(meta.presets[preset]?.knobs ?? {}) };
  const k = { ...KNOB_DEFAULTS, ...knobs };
  const diff = (Object.keys(KNOB_DEFAULTS) as KnobKey[]).filter((n) => k[n] !== ref[n]).map((n) => `${n}:${k[n]}`);
  const off = (Object.keys(levers) as (keyof Levers)[]).filter((n) => !levers[n] && meta.levers[n]);
  const on = (Object.keys(levers) as (keyof Levers)[]).filter((n) => levers[n] && !meta.levers[n]);
  const q = new URLSearchParams();
  if (diff.length) q.set("k", diff.join(";"));
  if (off.length) q.set("off", off.join(","));
  if (on.length) q.set("on", on.join(","));
  return q.toString().replace(/%3A/g, ":").replace(/%3B/g, ";").replace(/%2C/g, ",");
}

