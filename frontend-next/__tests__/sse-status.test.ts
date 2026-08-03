import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { connectHotspotStream } from "@/lib/sse";
import type { StreamStatus } from "@/lib/stream-status";

class StubEventSource {
  static instances: StubEventSource[] = [];
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;
  listeners: Record<string, (e: unknown) => void> = {};
  constructor(public url: string) { StubEventSource.instances.push(this); }
  addEventListener(type: string, fn: (e: unknown) => void) { this.listeners[type] = fn; }
  close() { this.closed = true; }
  emit(type: string, data: unknown) { this.listeners[type]?.({ data: JSON.stringify(data) }); }
}

beforeEach(() => {
  StubEventSource.instances = [];
  vi.stubGlobal("EventSource", StubEventSource);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const collect = () => {
  const seen: StreamStatus[] = [];
  const stop = connectHotspotStream("http://api", "tok", {
    onStatus: (s) => seen.push(s),
  });
  return { seen, stop, es: () => StubEventSource.instances.at(-1)! };
};

describe("connectHotspotStream status", () => {
  it("reports connecting immediately, then live on open", () => {
    const { seen, es, stop } = collect();
    expect(seen).toEqual(["connecting"]);
    es().onopen?.();
    expect(seen).toEqual(["connecting", "live"]);
    stop();
  });

  it("reports live when an event arrives", () => {
    const { seen, es, stop } = collect();
    es().emit("hotspot_created", { hotspot_id: 1 });
    expect(seen.at(-1)).toBe("live");
    stop();
  });

  it("reports reconnecting on error, then connecting when the retry opens", () => {
    const { seen, es, stop } = collect();
    es().onerror?.();
    expect(seen.at(-1)).toBe("reconnecting");
    vi.advanceTimersByTime(2000);   // past the ~1s backoff for attempt 0
    expect(seen.at(-1)).toBe("connecting");
    stop();
  });

  it("keeps backing off across repeated immediate drops", () => {
    // Regression guard: resetting `attempt` in onopen would make a server that
    // accepts-then-drops reconnect every ~1s forever instead of backing off.
    const { es, stop } = collect();
    es().onopen?.();
    es().onerror?.();
    vi.advanceTimersByTime(2000);
    const afterFirst = StubEventSource.instances.length;
    StubEventSource.instances.at(-1)!.onopen?.();
    StubEventSource.instances.at(-1)!.onerror?.();
    vi.advanceTimersByTime(1600);   // under the ~2s attempt-1 backoff
    expect(StubEventSource.instances.length).toBe(afterFirst);
    stop();
  });

  it("emits no status after the caller disconnects", () => {
    const { seen, es, stop } = collect();
    stop();
    es().onerror?.();
    expect(seen).toEqual(["connecting"]);
  });
});
