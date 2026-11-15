import { useState } from "react";
// llm.ts only type-imports web-llm, so this static import does not pull the model runtime into the page bundle
import { interpret, loadModel, MODEL_LABEL, MODEL_SIZE, webgpuAvailable } from "./llm";
import { describe, findCompany, parseScenario, type Scenario } from "./parse";

const EXAMPLES = [
  "Revenue falls 40% for a year and banks stop lending for 6 months",
  "Another 2008, but the company keeps paying dividends",
  "Rates up 3 points and wages up 5% for two years",
];

type AiState = "off" | "loading" | "ready" | "error";

/** Describe a crisis in plain English; the twin turns it into a scenario and simulates it. */
export function AskTwin({ names, onApply }: { names: Record<string, string>; onApply: (sc: Scenario) => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ lines: string[]; source: "rules" | "ai"; ticker?: string } | null>(null);
  const [miss, setMiss] = useState(false);
  const [ai, setAi] = useState<AiState>("off");
  const [progress, setProgress] = useState("");
  const [busy, setBusy] = useState(false);
  const [gpu] = useState(webgpuAvailable);

  const enableAi = async () => {
    setAi("loading");
    try {
      await loadModel((p) => setProgress(`${Math.round(p.progress * 100)}% · ${p.text.split(".")[0]}`));
      setAi("ready");
    } catch (e) {
      setProgress(String((e as Error).message ?? e).slice(0, 160));
      setAi("error");
    }
  };

  const run = async (q: string) => {
    const query = q.trim();
    if (!query) return;
    setBusy(true);
    setMiss(false);
    let sc: Scenario | null = null;
    let source: "rules" | "ai" = "rules";
    try {
      if (ai === "ready") {
        try {
          const out = await interpret(query);
          if (out && (Object.keys(out.knobs).length || Object.keys(out.levers).length)) { sc = { ...out, ticker: findCompany(query, names) }; source = "ai"; }
        } catch { /* fall back to the rules */ }
      }
      if (!sc) {
        const r = parseScenario(query, names);
        sc = r.matched ? r : null;
      }
    } finally {
      setBusy(false);
    }
    if (!sc) { setResult(null); setMiss(true); return; }
    setResult({ lines: describe(sc), source, ticker: sc.ticker });
    onApply(sc);
  };

  return (
    <div className="panel" style={{ padding: "16px 18px", marginBottom: 26 }}>
      <form onSubmit={(e) => { e.preventDefault(); run(text); }} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <label htmlFor="ask-twin" className="eyebrow" style={{ width: "100%" }}>Ask the twin: describe a crisis in your own words</label>
        <input id="ask-twin" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. What if Carnival's bookings halve for a year and debt markets close?"
          style={{ flex: "1 1 320px", padding: "9px 12px", fontSize: 14.5, border: "1px solid var(--rule-2)", borderRadius: 8, background: "var(--paper)", color: "var(--ink)" }} />
        <button className="btn" type="submit" disabled={busy || !text.trim()}>{busy ? "Thinking…" : "Run it"}</button>
      </form>
      <div className="chips" style={{ marginTop: 10 }}>
        {EXAMPLES.map((ex) => <button key={ex} type="button" className="chip" onClick={() => { setText(ex); run(ex); }}>{ex}</button>)}
      </div>

      {result && (
        <p className="sub" style={{ margin: "12px 0 0" }} aria-live="polite">
          <b>Understood{result.source === "ai" ? " by the on-device model" : ""}:</b> {result.lines.join("; ") || "no shock, baseline only"}
          {result.ticker ? ` · company ${result.ticker}` : ""}. Fine-tune it with the sliders.
        </p>
      )}
      {miss && <p className="sub" style={{ margin: "12px 0 0" }} aria-live="polite">I could not find a scenario in that. Mention revenue, rates, spreads, debt markets, costs or a named crisis such as a recession or 2008{ai === "off" && gpu ? ", or switch on the on-device model for free-form text" : ""}.</p>}

      <div className="muted" style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        {ai === "off" && gpu && <button type="button" className="btn-link" onClick={enableAi}>Understand free-form text with an on-device AI model</button>}
        {ai === "off" && gpu && <span>({MODEL_SIZE}, downloaded once, runs in your browser; nothing you type leaves it)</span>}
        {ai === "off" && !gpu && <span>Free-form understanding with an on-device AI model needs a browser with WebGPU, such as Chrome or Edge on a desktop.</span>}
        {ai === "loading" && <span><span className="busy-dot" /> Loading the model: {progress || "starting"}</span>}
        {ai === "ready" && <span>On-device model ready ({MODEL_LABEL}, WebGPU).</span>}
        {ai === "error" && <span>The model could not load here ({progress}); the built-in rules still work.</span>}
        <span>Language only chooses the scenario; every number on this page comes from the simulation.</span>
      </div>
    </div>
  );
}
