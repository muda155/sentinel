import { describe, it, expect } from "vitest";
import { fillColor, ringColor } from "@/lib/colors";

describe("fillColor (conf_score)", () => {
  it("green above 70", () => expect(fillColor(85)).toEqual([34, 197, 94, 200]));
  it("yellow at 40-70 inclusive boundaries", () => {
    expect(fillColor(40)).toEqual([234, 179, 8, 200]);
    expect(fillColor(70)).toEqual([234, 179, 8, 200]);
  });
  it("grey below 40", () => expect(fillColor(39.9)).toEqual([148, 163, 184, 200]));
});

describe("ringColor (alert_level)", () => {
  it("red for Critical", () => expect(ringColor("Critical")).toEqual([220, 38, 38, 255]));
  it("orange for High", () => expect(ringColor("High")).toEqual([249, 115, 22, 255]));
  it("transparent for Medium", () => expect(ringColor("Medium")).toEqual([0, 0, 0, 0]));
});
