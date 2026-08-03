import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render } from "@testing-library/react";
import Page from "@/app/page";
import type { Hotspot } from "@/lib/api";

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    token: "tok", user: { username: "tester", role: "admin" },
    hydrated: true, logout: vi.fn(),
  }),
}));
vi.mock("@/lib/i18n", () => ({ useT: () => ({ t: (k: string) => k }) }));
vi.mock("@/components/HotspotDetail", () => ({ default: () => null }));
vi.mock("@/components/LanguageToggle", () => ({ default: () => null }));
vi.mock("@/components/StreamStatus", () => ({ default: () => null }));

// Controllable useHotspots: the page mounts with no hotspots, then the test
// resolves them with act(), exactly like the first /hotspots response.
const hs = vi.hoisted(() => ({ setList: null as null | ((h: Hotspot[]) => void) }));
vi.mock("@/lib/useHotspots", async () => {
  const React = await import("react");
  return {
    useHotspots: () => {
      const [list, set] = React.useState<Hotspot[]>([]);
      hs.setList = set;
      return { hotspots: list, status: "live", lastEventAt: null };
    },
  };
});

const MATCH: Hotspot = {
  hotspot_id: 3546, lat: 10, lon: 20, conf_score: 60, convergence_score: 40,
  alert_level: "Medium", event_count: 2, name: "Kyiv, Ukraine",
  start_window: null, end_window: null, created_at: null, consistency_score: null,
};

const setUrl = (search: string) => {
  window.history.replaceState({}, "", `/${search}`);
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Page URL restoration", () => {
  it("does not strip ?h= during the load gap and keeps it after /hotspots resolves", async () => {
    setUrl("?h=3546");
    const spy = vi.spyOn(window.history, "replaceState");
    render(<Page />);

    // /hotspots has not resolved yet — the write-back must not have rewritten
    // the shared id out of the address bar (a copy in that window would
    // silently lose the hotspot).
    expect(spy).not.toHaveBeenCalled();

    await act(async () => { hs.setList!([MATCH]); });

    const calls = spy.mock.calls.map((c) => String(c[2]));
    expect(calls[calls.length - 1]).toContain("h=3546");
  });

  it("keeps ?h= during the gap even for a stale id, then drops it after resolution", async () => {
    setUrl("?h=999");
    const spy = vi.spyOn(window.history, "replaceState");
    render(<Page />);
    expect(spy).not.toHaveBeenCalled();

    await act(async () => { hs.setList!([MATCH]); });   // no hotspot 999

    // Resolution concluded there is no match — only now is the id dropped.
    const last = String(spy.mock.calls.at(-1)?.[2]);
    expect(last).not.toContain("h=999");
  });

  it("still writes URL state immediately on a plain load", async () => {
    setUrl("");
    const spy = vi.spyOn(window.history, "replaceState");
    render(<Page />);
    expect(spy).toHaveBeenCalled();
  });
});
