import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StackedBar from "@/components/StackedBar";

describe("StackedBar", () => {
  it("reports unscaled segment values in the aria-label when within the cap", () => {
    render(
      <StackedBar
        label="Confidence"
        max={100}
        segments={[
          { label: "density", value: 60, color: "#fff" },
          { label: "diversity", value: 20, color: "#000" },
        ]}
      />,
    );
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "Confidence: density 60.0, diversity 20.0",
    );
  });

  it("scales the aria-label values when the parts exceed the cap", () => {
    // 100 + 25 = 125 > 100, so scale = 100/125 = 0.8 -> 80.0 and 20.0.
    // The non-visual reading must match the drawn widths, not the raw inputs.
    render(
      <StackedBar
        label="Convergence"
        max={100}
        segments={[
          { label: "types", value: 100, color: "#fff" },
          { label: "count", value: 25, color: "#000" },
        ]}
      />,
    );
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "Convergence: types 80.0, count 20.0",
    );
  });
});
