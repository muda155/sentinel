import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => dict[k as keyof typeof dict] ?? k }) };
});

import ScoreHelp from "@/components/ScoreHelp";

const renderHelp = () =>
  render(<ScoreHelp titleKey="help.confidence.title" bodyKeys={["help.confidence.what"]} />);

describe("ScoreHelp", () => {
  it("is collapsed until activated", () => {
    renderHelp();
    expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("reveals the explanation on click", () => {
    renderHelp();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("tooltip").textContent).toContain(viLocale["help.confidence.what"]);
  });

  it("closes on Escape", () => {
    renderHelp();
    fireEvent.click(screen.getByRole("button"));
    fireEvent.keyDown(screen.getByRole("tooltip"), { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
