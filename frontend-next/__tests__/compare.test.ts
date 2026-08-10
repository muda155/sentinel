import { describe, expect, it } from "vitest";
import { buildComparison, deltaTone } from "@/lib/compare";
import type { WindowMetrics } from "@/lib/window-metrics";
import type { WindowConsistency } from "@/lib/window-consistency";

const m = (o: Partial<WindowMetrics>): WindowMetrics => ({
  eventCount: 0, uniqueDomains: 0, maxFatalities: null, meanTone: null,
  sourceDensity: 0, diversity: 0, conf: 0,
  convergence: { mode: "typesOnly", types: 0, events: 0 }, ...o,
});

const noScore: WindowConsistency = { mode: "countsOnly", outcomes: [] };

describe("buildComparison", () => {
  it("reports the delta and direction from A to B", () => {
    const rows = buildComparison({
      a: m({ eventCount: 18 }), b: m({ eventCount: 24 }),
      consistencyA: noScore, consistencyB: noScore,
      confTrusted: true, consistencyTrusted: false,
    });
    const events = rows.find((r) => r.key === "events")!;
    expect(events.a).toBe(18);
    expect(events.b).toBe(24);
    expect(events.delta).toBe(6);
    expect(events.direction).toBe("up");
  });

  it("marks an unchanged metric flat, not up", () => {
    const rows = buildComparison({
      a: m({ eventCount: 5 }), b: m({ eventCount: 5 }),
      consistencyA: noScore, consistencyB: noScore,
      confTrusted: true, consistencyTrusted: false,
    });
    expect(rows.find((r) => r.key === "events")!.direction).toBe("flat");
  });

  it("marks the confidence row untrusted when the reconstruction failed", () => {
    const rows = buildComparison({
      a: m({ conf: 70 }), b: m({ conf: 80 }),
      consistencyA: noScore, consistencyB: noScore,
      confTrusted: false, consistencyTrusted: false,
    });
    expect(rows.find((r) => r.key === "conf")!.trusted).toBe(false);
  });

  it("gives the confidence row no direction when a side is empty", () => {
    const rows = buildComparison({
      a: m({ conf: null }), b: m({ conf: 70 }),
      consistencyA: noScore, consistencyB: noScore,
      confTrusted: true, consistencyTrusted: false,
    });
    const row = rows.find((r) => r.key === "conf")!;
    expect(row.delta).toBeNull();
    expect(row.direction).toBe("none");
  });

  it("gives a null delta and no direction when a side has no value", () => {
    const rows = buildComparison({
      a: m({ maxFatalities: null }), b: m({ maxFatalities: 9 }),
      consistencyA: noScore, consistencyB: noScore,
      confTrusted: true, consistencyTrusted: false,
    });
    const row = rows.find((r) => r.key === "fatalities")!;
    expect(row.delta).toBeNull();
    expect(row.direction).toBe("none");
  });

  it("includes a consistency row only when both windows produced a score", () => {
    const scored: WindowConsistency = { mode: "score", score: 80, outcomes: [] };
    const without = buildComparison({
      a: m({}), b: m({}), consistencyA: scored, consistencyB: noScore,
      confTrusted: true, consistencyTrusted: true,
    });
    expect(without.find((r) => r.key === "consistency")).toBeUndefined();

    const with_ = buildComparison({
      a: m({}), b: m({}), consistencyA: scored, consistencyB: { mode: "score", score: 60, outcomes: [] },
      confTrusted: true, consistencyTrusted: true,
    });
    expect(with_.find((r) => r.key === "consistency")!.delta).toBeCloseTo(-20, 6);
  });
});

describe("deltaTone", () => {
  it("treats more confidence and consistency as good, more fatalities as bad", () => {
    expect(deltaTone("conf", "up")).toBe("good");
    expect(deltaTone("conf", "down")).toBe("bad");
    expect(deltaTone("consistency", "up")).toBe("good");
    expect(deltaTone("fatalities", "up")).toBe("bad");
    expect(deltaTone("fatalities", "down")).toBe("good");
  });

  it("is neutral for metrics with no inherent polarity", () => {
    expect(deltaTone("events", "up")).toBe("neutral");
    expect(deltaTone("domains", "down")).toBe("neutral");
    expect(deltaTone("tone", "up")).toBe("neutral");
  });

  it("is neutral for flat and none", () => {
    expect(deltaTone("conf", "flat")).toBe("neutral");
    expect(deltaTone("conf", "none")).toBe("neutral");
  });
});
