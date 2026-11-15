import { Section } from "../ui";

/** For a route such as #twin/ZZZZ whose ticker is not in the index. */
export function MissingTwin({ ticker, onSearch, onCompare }: { ticker: string; onSearch: () => void; onCompare: () => void }) {
  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">Company</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>No twin for {ticker}</h1>
        <p className="lede">This site has a twin for each S&amp;P 500 company outside financials and real estate that files
          under US-GAAP in USD. {ticker} is not one of them, or the ticker is misspelt.</p>
        <div style={{ display: "flex", gap: 12, marginTop: 22, flexWrap: "wrap" }}>
          <button className="btn btn-primary btn-lg" onClick={onSearch}>Find a company</button>
          <button className="btn btn-lg" onClick={onCompare}>See all companies</button>
        </div>
      </Section>
    </div>
  );
}
