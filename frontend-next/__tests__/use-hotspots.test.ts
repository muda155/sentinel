import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useHotspots } from "@/lib/useHotspots";
import type { Hotspot } from "@/lib/api";

const hotspotsMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, hotspots: hotspotsMock } };
});

vi.mock("@/lib/sse", () => ({
  connectHotspotStream: vi.fn(() => () => {}),
}));

const HOTSPOT: Hotspot = {
  hotspot_id: 1, lat: 10, lon: 20, conf_score: 60, convergence_score: 40,
  alert_level: "Medium", event_count: 2, name: "Kyiv, Ukraine",
  start_window: null, end_window: null, created_at: null, consistency_score: null,
};

beforeEach(() => {
  hotspotsMock.mockReset();
});

const flush = async () => {
  await act(async () => {});
};

describe("useHotspots", () => {
  it("does not fetch or latch settled while token is null (pre-hydration)", async () => {
    // auth.tsx starts token: null and hydrates in an effect, so the hook's
    // first pass runs unauthenticated. That 401 must not trip `settled` —
    // the page's ?h= restore gate would then open against an empty list and
    // strip the shared id before the authenticated query lands. (It would
    // also burn a /hotspots rate-limit token for a request that always 401s.)
    hotspotsMock.mockRejectedValue(new Error("401"));
    const { result } = renderHook(() => useHotspots(null));
    await flush();
    expect(hotspotsMock).not.toHaveBeenCalled();
    expect(result.current.settled).toBe(false);
  });

  it("latches settled once an authenticated fetch succeeds", async () => {
    hotspotsMock.mockResolvedValue([HOTSPOT]);
    const { result } = renderHook(() => useHotspots("tok"));
    await flush();
    expect(hotspotsMock).toHaveBeenCalledWith("tok");
    expect(result.current.settled).toBe(true);
    expect(result.current.hotspots).toEqual([HOTSPOT]);
  });

  it("latches settled even when an authenticated fetch fails", async () => {
    hotspotsMock.mockRejectedValue(new Error("500"));
    const { result } = renderHook(() => useHotspots("tok"));
    await flush();
    expect(hotspotsMock).toHaveBeenCalledWith("tok");
    expect(result.current.settled).toBe(true);
    expect(result.current.hotspots).toEqual([]);
  });
});
