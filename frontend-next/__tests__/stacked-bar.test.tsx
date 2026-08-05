import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StackedBar from "@/components/StackedBar";

describe("StackedBar", () => {
  it("reports raw segment values in the aria-label when within the cap", () => {
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

  it("keeps the aria-label and legend on the same raw figures when clamped, and appends the clamp note", () => {
    // 100 + 25 = 125 > 100, so the track scales by 100/125 = 0.8. The rects
    // are scaled but the aria-label and the legend must both report the raw
    // 100.0 / 25.0 — a screen reader that hears 80.0 / 20.0 would contradict
    // the legend sitting next to the bar. The clamp note explains the gap.
    render(
      <StackedBar
        label="Convergence"
        max={100}
        clampNote="Capped at 100"
        segments={[
          { label: "types", value: 100, color: "#fff" },
          { label: "count", value: 25, color: "#000" },
        ]}
      />,
    );
    const img = screen.getByRole("img");
    expect(img.getAttribute("aria-label")).toBe(
      "Convergence: types 100.0, count 25.0 — Capped at 100",
    );
    // legend rows carry the same raw figures as the aria-label
    expect(screen.getByText(/types/).textContent).toContain("100.0");
    expect(screen.getByText(/count/).textContent).toContain("25.0");
  });

  it("omits the clamp note when the parts fit within the cap", () => {
    render(
      <StackedBar
        label="Confidence"
        max={100}
        clampNote="Capped at 100"
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
});
