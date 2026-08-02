import { describe, it, expect } from "vitest";
import { formatTone, formatIntensity, maxFatalities, meanTone } from "@/lib/severity";

describe("severity formatting", () => {
  it("formats tone and intensity to one decimal, passing through null", () => {
    expect(formatTone(-5.25)).toBe("-5.3");
    expect(formatTone(null)).toBeNull();
    expect(formatIntensity(-8)).toBe("-8.0");
    expect(formatIntensity(null)).toBeNull();
  });

  it("aggregates fatalities as a max, ignoring nulls", () => {
    expect(maxFatalities([{ fatalities: 3 }, { fatalities: null }, { fatalities: 12 }] as never)).toBe(12);
    expect(maxFatalities([{ fatalities: null }] as never)).toBeNull();
    expect(maxFatalities([])).toBeNull();
  });

  it("averages tone over events that have one", () => {
    expect(meanTone([{ avg_tone: -4 }, { avg_tone: -6 }, { avg_tone: null }] as never)).toBe(-5);
    expect(meanTone([{ avg_tone: null }] as never)).toBeNull();
  });
});
