import { describe, it, expect } from "vitest";
import { serializeState, parseState, DEFAULT_URL_STATE, type UrlState } from "@/lib/url-state";
import { DEFAULT_FILTERS } from "@/lib/filters";

const withFilters = (over: Partial<UrlState["filters"]>): UrlState => ({
  ...DEFAULT_URL_STATE,
  filters: { ...DEFAULT_FILTERS, alertLevels: new Set(DEFAULT_FILTERS.alertLevels), ...over },
});

describe("serializeState", () => {
  it("emits an empty string for the default state", () => {
    // Defaults are omitted so a shared link stays readable and a plain
    // visit to "/" is not immediately rewritten with noise.
    expect(serializeState(DEFAULT_URL_STATE)).toBe("");
  });
  it("emits only the keys that differ from the default", () => {
    expect(serializeState({ ...DEFAULT_URL_STATE, hotspotId: 3546 })).toBe("h=3546");
    expect(serializeState(withFilters({ minConf: 65 }))).toBe("conf=65");
    expect(serializeState(withFilters({ timeWindow: "24h" }))).toBe("win=24h");
    expect(serializeState({ ...DEFAULT_URL_STATE, heat: true })).toBe("heat=1");
    expect(serializeState({ ...DEFAULT_URL_STATE, globe: true })).toBe("globe=1");
  });
  it("emits alert levels only when the selection is a strict subset", () => {
    expect(serializeState(withFilters({ alertLevels: new Set(["Critical", "High"]) }))).toBe("alert=Critical%2CHigh");
    expect(serializeState(withFilters({ alertLevels: new Set() }))).toBe("alert=");
  });
});

describe("parseState", () => {
  it("returns the defaults for an empty search string", () => {
    const s = parseState("");
    expect(s.hotspotId).toBeNull();
    expect(s.filters.minConf).toBe(DEFAULT_FILTERS.minConf);
    expect(s.filters.timeWindow).toBe(DEFAULT_FILTERS.timeWindow);
    expect([...s.filters.alertLevels].sort()).toEqual(["Critical", "High", "Medium"]);
    expect(s.heat).toBe(false);
    expect(s.globe).toBe(false);
  });
  it("accepts a leading '?'", () => {
    expect(parseState("?h=42").hotspotId).toBe(42);
  });
  it("round-trips every field", () => {
    const start: UrlState = {
      hotspotId: 3546, heat: true, globe: true,
      filters: { minConf: 15, timeWindow: "30d", alertLevels: new Set(["Critical"]) },
    };
    const back = parseState(serializeState(start));
    expect(back.hotspotId).toBe(3546);
    expect(back.heat).toBe(true);
    expect(back.globe).toBe(true);
    expect(back.filters.minConf).toBe(15);
    expect(back.filters.timeWindow).toBe("30d");
    expect([...back.filters.alertLevels]).toEqual(["Critical"]);
  });
  it("falls back to defaults on hostile or malformed input", () => {
    // A pasted/truncated link must never produce NaN sliders or a crash.
    expect(parseState("h=abc").hotspotId).toBeNull();
    expect(parseState("h=-5").hotspotId).toBeNull();
    expect(parseState("conf=999").filters.minConf).toBe(DEFAULT_FILTERS.minConf);
    expect(parseState("conf=nope").filters.minConf).toBe(DEFAULT_FILTERS.minConf);
    expect(parseState("win=17y").filters.timeWindow).toBe(DEFAULT_FILTERS.timeWindow);
    expect([...parseState("alert=Critical,Nonsense").filters.alertLevels]).toEqual(["Critical"]);
  });
  it("distinguishes an absent alert param from an empty one", () => {
    expect(parseState("").filters.alertLevels.size).toBe(3);
    expect(parseState("alert=").filters.alertLevels.size).toBe(0);
  });
  it("returns a fresh Set each call", () => {
    // Sharing DEFAULT_FILTERS.alertLevels by reference would let a checkbox
    // toggle mutate the module-level default for the rest of the session.
    const a = parseState("");
    const b = parseState("");
    expect(a.filters.alertLevels).not.toBe(b.filters.alertLevels);
    expect(a.filters.alertLevels).not.toBe(DEFAULT_FILTERS.alertLevels);
  });
});
