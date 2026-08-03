import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useRawEvents } from "@/lib/useRawEvents";
import type { EventFeature } from "@/lib/api";
import type { Bbox } from "@/lib/events-layer";
import type { TimeWindow } from "@/lib/filters";

const eventsMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, events: eventsMock } };
});

const feat = (id: number): EventFeature => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [1, 2] },
  properties: {
    event_id: id, event_date: "2026-08-01T00:00:00.000Z", cameo_code: null,
    country_code: null, url: null, title: null,
  },
});

const COLLECTION = (ids: number[]) => ({
  type: "FeatureCollection" as const,
  features: ids.map(feat),
  next_cursor: null,
});

const BBOX: Bbox = { sw_lat: 10, sw_lon: 20, ne_lat: 11, ne_lon: 21 };

beforeEach(() => {
  eventsMock.mockReset();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

// Fire the 800ms trailing debounce and flush the promise chain inside act.
const flush = async () => {
  await act(async () => { await vi.advanceTimersByTimeAsync(800); });
};

describe("useRawEvents", () => {
  it("fetches once per viewport, after the debounce quiet period", async () => {
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { result } = renderHook(() => useRawEvents("tok", true, BBOX, "7d"));
    expect(eventsMock).not.toHaveBeenCalled();   // still inside the debounce
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(1);
    expect(result.current.features).toHaveLength(1);
    expect(result.current.failed).toBe(false);
  });

  it("does not refetch while the quantized key is unchanged", async () => {
    // A fresh bbox object with the same values simulates any same-cell render.
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { rerender } = renderHook(
      ({ bbox }) => useRawEvents("tok", true, bbox, "7d"),
      { initialProps: { bbox: { ...BBOX } } });
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(1);

    rerender({ bbox: { ...BBOX } });
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(1);
  });

  it("refetches when the time window changes", async () => {
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { rerender } = renderHook(
      ({ win }) => useRawEvents("tok", true, BBOX, win),
      { initialProps: { win: "7d" as TimeWindow } });
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(1);

    rerender({ win: "24h" });
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(2);
  });

  it("clears the layer and stops fetching while disabled", async () => {
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { result, rerender } = renderHook(
      ({ enabled }) => useRawEvents("tok", enabled, BBOX, "7d"),
      { initialProps: { enabled: true } });
    await flush();
    expect(result.current.features).toHaveLength(1);

    rerender({ enabled: false });
    expect(result.current.features).toHaveLength(0);
    expect(result.current.failed).toBe(false);
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(1);
  });

  it("flags a failed fetch and retries it on a same-key re-run", async () => {
    // Regression guard (review finding 2): a transient 429/network error must
    // not be cached as "fetched", or the layer stays empty for the whole cell.
    eventsMock
      .mockRejectedValueOnce(new Error("429"))
      .mockResolvedValueOnce(COLLECTION([1]));
    const { result, rerender } = renderHook(
      ({ bbox }) => useRawEvents("tok", true, bbox, "7d"),
      { initialProps: { bbox: { ...BBOX } } });
    await flush();
    expect(result.current.failed).toBe(true);
    expect(result.current.features).toHaveLength(0);
    expect(eventsMock).toHaveBeenCalledTimes(1);

    rerender({ bbox: { ...BBOX } });   // same key, fresh effect
    await flush();
    expect(eventsMock).toHaveBeenCalledTimes(2);
    expect(result.current.failed).toBe(false);
    expect(result.current.features).toHaveLength(1);
  });

  it("cancels a pending debounced fetch on unmount", async () => {
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { unmount } = renderHook(() => useRawEvents("tok", true, BBOX, "7d"));
    unmount();
    await flush();
    expect(eventsMock).not.toHaveBeenCalled();
  });

  it("does nothing without a token or bbox", async () => {
    eventsMock.mockResolvedValue(COLLECTION([1]));
    const { result } = renderHook(() => useRawEvents(null, true, null, "7d"));
    await flush();
    expect(eventsMock).not.toHaveBeenCalled();
    expect(result.current.features).toHaveLength(0);
    expect(result.current.failed).toBe(false);
  });
});
