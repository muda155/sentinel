import { describe, it, expect } from "vitest";
import { bucketByDay } from "@/lib/sparkline";

const ev = (iso: string) => ({ event_date: iso }) as never;

describe("bucketByDay", () => {
  it("returns one bucket per day, oldest first, zero-filled", () => {
    const now = new Date("2026-08-03T00:00:00Z");
    const out = bucketByDay([ev("2026-08-03T05:00:00Z"), ev("2026-08-01T05:00:00Z")], 3, now);
    expect(out.map((b) => b.count)).toEqual([1, 0, 1]);
    expect(out).toHaveLength(3);
  });

  it("ignores events older than the window", () => {
    const now = new Date("2026-08-03T00:00:00Z");
    const out = bucketByDay([ev("2026-07-01T05:00:00Z")], 3, now);
    expect(out.map((b) => b.count)).toEqual([0, 0, 0]);
  });
});
