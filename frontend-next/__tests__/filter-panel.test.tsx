import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";
import { DEFAULT_FILTERS } from "@/lib/filters";

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => dict[k as keyof typeof dict] ?? k }) };
});

vi.mock("@/lib/whatsnew", () => ({ markSeen: vi.fn() }));

import FilterPanel from "@/components/FilterPanel";
import { markSeen } from "@/lib/whatsnew";

const renderPanel = (newCount = 1) => {
  const onChange = vi.fn();
  render(
    <FilterPanel filters={DEFAULT_FILTERS} onChange={onChange} visible={1} total={2} newCount={newCount} />,
  );
  return { onChange };
};

describe("FilterPanel", () => {
  it("renders a collapsed trigger with title, counter and new chip", () => {
    renderPanel();
    const trigger = screen.getByRole("button", { name: /Bộ lọc/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText(viLocale["filter.title"])).toBeTruthy();
    expect(
      screen.getByText(viLocale["filter.showing"].replace("{n}", "1").replace("{m}", "2")),
    ).toBeTruthy();
    expect(screen.getByText(viLocale["whatsnew.new"].replace("{n}", "1"))).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("hides the new chip when nothing is new", () => {
    renderPanel(0);
    expect(screen.queryByText(/mới/)).toBeNull();
  });

  it("opens the popover on trigger click", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Bộ lọc/ }));
    const dialog = screen.getByRole("dialog", { name: viLocale["filter.title"] });
    expect(dialog).toBeTruthy();
    expect(screen.getByText(new RegExp(viLocale["filter.confidence"]))).toBeTruthy();
    expect(screen.getByText(viLocale["filter.alertLevel"])).toBeTruthy();
    expect(screen.getByText(viLocale["filter.timeWindow"])).toBeTruthy();
    expect(screen.getByText(viLocale["filter.reset"])).toBeTruthy();
    expect(screen.getByText(viLocale["whatsnew.markSeen"])).toBeTruthy();
  });

  it("closes the popover on Escape", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Bộ lọc/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is inert to Escape while closed (listener registered only when open)", () => {
    renderPanel();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    // reopening after a closed-state Escape still works
    fireEvent.click(screen.getByRole("button", { name: /Bộ lọc/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("marks seen from inside the popover", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Bộ lọc/ }));
    fireEvent.click(screen.getByText(viLocale["whatsnew.markSeen"]));
    expect(markSeen).toHaveBeenCalledTimes(1);
  });
});
