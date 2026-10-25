import { Fragment, lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { CommandPalette } from "./CommandPalette";
import { loadCompany, loadIndex, type Company, type Index } from "./data";
import { prettyName, shortcutLabel } from "./format";
import { useHashState } from "./hooks";
import { IconChevron, IconMoon, IconSun, Skeleton, Wordmark } from "./ui";
import { OverviewView } from "./views/OverviewView";

// Secondary views load on demand so the landing page ships less JavaScript.
const StressLab = lazy(() => import("./views/StressLab").then((m) => ({ default: m.StressLab })));
const TimeMachineView = lazy(() => import("./views/TimeMachineView").then((m) => ({ default: m.TimeMachineView })));
const VersusView = lazy(() => import("./views/VersusView").then((m) => ({ default: m.VersusView })));
const CompareView = lazy(() => import("./views/CompareView").then((m) => ({ default: m.CompareView })));
const BacktestView = lazy(() => import("./views/BacktestView").then((m) => ({ default: m.BacktestView })));
const MachineView = lazy(() => import("./views/MachineView").then((m) => ({ default: m.MachineView })));
const MethodView = lazy(() => import("./views/MethodView").then((m) => ({ default: m.MethodView })));
const ChangesView = lazy(() => import("./views/ChangesView").then((m) => ({ default: m.ChangesView })));
import { TwinView } from "./views/TwinView";

const NAV = [
  ["overview", "Overview"], ["changes", "This week"], ["twin", "Company"], ["stress", "Stress lab"], ["time", "Time machine"],
  ["versus", "Compare"], ["compare", "Matrix"], ["backtest", "Evidence"], ["method", "Method"],
] as const;
const VIEWS = new Set<string>([...NAV.map(([k]) => k), "machine"]);
const COMPANY_VIEWS = new Set(["twin", "stress", "machine", "time"]);
const LIVE_API = import.meta.env.DEV;

function useTheme() {
  const [theme, setTheme] = useState<string | null>(() => {
    try { return localStorage.getItem("theme"); } catch { return null; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { if (theme) localStorage.setItem("theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);
  const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  return [dark, () => setTheme(dark ? "light" : "dark")] as const;
}

export default function App() {
  const [route, setRoute] = useHashState("overview");
  const [pathPart, query = ""] = route.split("?");
  const [viewRaw, tickerRaw, presetRaw] = pathPart.split("/");
  const view = VIEWS.has(viewRaw) ? viewRaw : "overview";
  const [lastTicker, setLastTicker] = useState("CCL");
  const ticker = (tickerRaw || lastTicker).toUpperCase();
  const [index, setIndex] = useState<Index | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [dark, toggleTheme] = useTheme();

  useEffect(() => { loadIndex().then(setIndex).catch((e) => setError(String(e))); }, []);
  useEffect(() => {
    if (!COMPANY_VIEWS.has(view)) return;
    setError(null);
    setLastTicker(ticker);
    loadCompany(ticker).then(setCompany).catch((e) => setError(String(e.message ?? e)));
  }, [ticker, view]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [view]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.matches?.("input, textarea, select");
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); setPalette(true); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "?") setHelp((h) => !h);
      else if (e.key === "Escape") setHelp(false);
      else if (e.key === "t") toggleThemeRef.current();
      else if (/^[1-9]$/.test(e.key) && NAV[+e.key - 1]) navRef.current(NAV[+e.key - 1][0]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    const name = company && COMPANY_VIEWS.has(view) ? `${company.ticker} · ` : "";
    document.title = `${name}FinTwin`;
  }, [company, view]);

  const navRef = useRef<(v: string) => void>(() => {});
  const toggleThemeRef = useRef<() => void>(() => {});
  const go = (v: string, t?: string, p?: string) => setRoute([v, COMPANY_VIEWS.has(v) ? (t ?? ticker) : undefined, p].filter(Boolean).join("/"));
  navRef.current = (v: string) => go(v);
  toggleThemeRef.current = toggleTheme;
  const openCompany = (t: string) => go(COMPANY_VIEWS.has(view) ? view : "twin", t);
  const entry = index?.companies[ticker];
  const names = useMemo(() => Object.fromEntries(Object.entries(index?.companies ?? {}).map(([t2, e]) => [t2, prettyName(e.name)])), [index]);

  return (
    <div className="app">
      <div className="masthead-bar">
        <header className="bar">
          <button className="wordmark" onClick={() => go("overview")} aria-label="FinTwin home"><Wordmark /></button>
          <nav className="nav" aria-label="Sections">
            {NAV.map(([k, label]) => (
              <button key={k} aria-current={view === k ? "page" : undefined} onClick={() => go(k)}>{label}</button>
            ))}
          </nav>
          <div className="bar-actions">
            <button className="switcher" onClick={() => setPalette(true)} title="Change company">
              <span className="tk">{ticker}</span>
              <span className="nm">{entry ? prettyName(entry.name) : "Find a company"}</span>
              <span className="kbd">{shortcutLabel}</span>
              <IconChevron />
            </button>
            <a className="star-btn" href="https://github.com/SpiliosDimakopoulos/fintwin" target="_blank" rel="noreferrer" aria-label="Star FinTwin on GitHub" title="Star FinTwin on GitHub">
              <span aria-hidden="true">★</span><span className="star-label">Star</span>
            </a>
            <button className="icon-btn" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
              {dark ? <IconSun /> : <IconMoon />}
            </button>
          </div>
        </header>
      </div>

      {index && <CommandPalette index={index} open={palette} onClose={() => setPalette(false)} onPick={openCompany} liveEnabled={LIVE_API} />}

      <main className="page">
        {error && <p className="callout" style={{ marginBottom: 24 }}>{error}</p>}
        {!index ? <Skeleton h={420} /> : (
          <Suspense fallback={<Skeleton h={520} />}>
            {view === "overview" && <OverviewView index={index} onOpen={(t) => go("twin", t)} onGo={(v) => go(v)} onStress={(p) => go("stress", "CCL", p)} />}
            {COMPANY_VIEWS.has(view) && (!company || company.ticker !== ticker) && !error && <Skeleton h={520} />}
            {view === "twin" && company?.ticker === ticker && (
              <TwinView c={company} meta={index.meta} index={index} onStress={(p) => go("stress", ticker, p)} onMachine={() => go("machine", ticker)} onOpen={(t) => go("twin", t)} onRewind={() => go("time", ticker)} />
            )}
            {view === "stress" && company?.ticker === ticker && (
              <StressLab key={ticker} c={company} meta={index.meta} preset={presetRaw ?? "pandemic"} query={query}
                setPreset={(p, q) => history.replaceState(null, "", `#${["stress", ticker, p].join("/")}${q ? `?${q}` : ""}`)}
                names={names} onCompany={(t2, q) => setRoute(`stress/${t2}/custom${q ? `?${q}` : ""}`)} />
            )}
            {view === "machine" && company?.ticker === ticker && <MachineView c={company} meta={index.meta} />}
            {view === "time" && company?.ticker === ticker && <TimeMachineView key={ticker} ticker={ticker} name={company.name} meta={index.meta} />}
            {view === "versus" && <VersusView index={index} pair={[tickerRaw, presetRaw]} onPair={(a, b2) => history.replaceState(null, "", `#versus/${a}/${b2}`)} onOpen={(t) => go("twin", t)} />}
            {view === "compare" && <CompareView index={index} onOpen={(t) => go("twin", t)} />}
            {view === "backtest" && <BacktestView onOpen={(t) => go("twin", t)} />}
            {view === "method" && <MethodView />}
            {view === "changes" && <ChangesView onOpen={(t) => go("twin", t)} />}
          </Suspense>
        )}
      </main>

      {help && (
        <div className="palette-backdrop" onMouseDown={() => setHelp(false)}>
          <div className="palette fade-in" style={{ padding: "18px 20px" }} role="dialog" aria-label="Keyboard shortcuts" onMouseDown={(e) => e.stopPropagation()}>
            <div className="eyebrow" style={{ marginBottom: 12 }}>Keyboard shortcuts</div>
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "10px 18px", margin: 0 }}>
              {[[`${shortcutLabel} or /`, "Find a company"], [`1 – ${NAV.length}`, NAV.map(([, l]) => l).join(" · ")], ["T", "Toggle light and dark"], ["?", "Show or hide this panel"], ["Esc", "Close"]].map(([k, d]) => (
                <Fragment key={k}><dt><span className="kbd">{k}</span></dt><dd className="sub" style={{ margin: 0 }}>{d}</dd></Fragment>
              ))}
            </dl>
          </div>
        </div>
      )}

      <footer className="footer">
        <span><span className="live-dot" style={{ background: "var(--good)" }} />Data rebuilt {index?.meta.generated} from SEC EDGAR and FRED · refreshes automatically every Monday. Research project, not investment advice.</span>
        <span><button className="btn-link" onClick={() => setHelp(true)}>Shortcuts <span className="kbd">?</span></button> · <a href="https://github.com/SpiliosDimakopoulos/fintwin" target="_blank" rel="noreferrer">Source</a> · <a href="https://github.com/SpiliosDimakopoulos/fintwin/blob/main/docs/paper/fintwin.pdf" target="_blank" rel="noreferrer">Paper</a></span>
      </footer>
    </div>
  );
}
