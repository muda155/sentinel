import { describe, it, expect } from "vitest";
import { gridCellTooltip, CELL_PICK_LAYER_ID } from "@/lib/map-tooltip";

const t = (key: string) => key;

const cell = {
  cell_id: "34_31", lat: 31.5, lon: 34.4,
  convergence_score: 72.4, alert_level: "High", total_events: 9,
};

describe("gridCellTooltip", () => {
  it("returns null when nothing is picked", () => {
    expect(gridCellTooltip({ layer: null, object: null }, t)).toBeNull();
  });

  it("ignores picks from other layers", () => {
    expect(
      gridCellTooltip({ layer: { id: "hotspots" }, object: cell }, t),
    ).toBeNull();
  });

  it("reports convergence, alert level and event count for a cell", () => {
    const tip = gridCellTooltip(
      { layer: { id: CELL_PICK_LAYER_ID }, object: cell }, t,
    );
    expect(tip?.text).toContain("72");
    expect(tip?.text).toContain("High");
    expect(tip?.text).toContain("9");
  });

  it("rounds convergence to a whole number", () => {
    const tip = gridCellTooltip(
      { layer: { id: CELL_PICK_LAYER_ID }, object: cell }, t,
    );
    expect(tip?.text).not.toContain("72.4");
  });
});
