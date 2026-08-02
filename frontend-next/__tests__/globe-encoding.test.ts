import { describe, it, expect } from "vitest";
import { pointAltitude, pointRadius } from "@/lib/globe-encoding";

describe("globe alert encoding", () => {
  it("ranks Critical > High > Medium on both channels", () => {
    expect(pointAltitude("Critical")).toBeGreaterThan(pointAltitude("High"));
    expect(pointAltitude("High")).toBeGreaterThan(pointAltitude("Medium"));
    expect(pointRadius("Critical")).toBeGreaterThan(pointRadius("High"));
    expect(pointRadius("High")).toBeGreaterThan(pointRadius("Medium"));
  });
  it("exact values", () => {
    expect(pointAltitude("Critical")).toBe(0.06);
    expect(pointAltitude("High")).toBe(0.03);
    expect(pointAltitude("Medium")).toBe(0.01);
    expect(pointRadius("Critical")).toBe(0.6);
    expect(pointRadius("High")).toBe(0.45);
    expect(pointRadius("Medium")).toBe(0.3);
  });
});
