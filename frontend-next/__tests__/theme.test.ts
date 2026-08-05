import { describe, expect, it } from "vitest";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";
import {
  FILL_GREEN, FILL_GREY, FILL_YELLOW, RING_ORANGE, RING_RED,
} from "@/lib/colors";

describe("theme tokens", () => {
  it("never restates an FR-13 encoding colour", () => {
    // lib/colors.ts is the single source of truth for marker fill/ring.
    // A duplicate here would let the map and the chrome drift apart silently.
    const encoding = [FILL_GREEN, FILL_YELLOW, FILL_GREY, RING_RED, RING_ORANGE]
      .map((c) => c.toLowerCase());
    for (const value of Object.values(COLOR)) {
      expect(encoding).not.toContain(value.toLowerCase());
    }
  });

  it("exposes every scale the panels need", () => {
    expect(Object.keys(SPACE)).toEqual(["xs", "sm", "md", "lg", "xl"]);
    expect(Object.keys(RADIUS)).toEqual(["sm", "md", "lg"]);
    expect(FONT.xs).toBeLessThan(FONT.base);
    expect(FONT.base).toBeLessThan(FONT.xl);
  });

  it("uses six-digit lowercase hex so the equality guard above cannot be fooled", () => {
    for (const value of Object.values(COLOR)) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});
