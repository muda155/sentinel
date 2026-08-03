import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";
import type { Hotspot } from "@/lib/api";

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => dict[k as keyof typeof dict] ?? k }) };
});

import TriageRail from "@/components/TriageRail";

const h = (over: Partial<Hotspot>): Hotspot => ({
  hotspot_id: 1, lat: 0, lon: 0, conf_score: 50, convergence_score: 50,
  alert_level: "Medium", event_count: 3, consistency_score: null, name: null,
  start_window: null, end_window: null, created_at: null, ...over,
});

const data = [
  h({ hotspot_id: 1, name: "Kyiv, Ukraine", alert_level: "Critical", conf_score: 82 }),
  h({ hotspot_id: 2, name: null, alert_level: "Medium", conf_score: 31 }),
];

const renderRail = (over: Partial<React.ComponentProps<typeof TriageRail>> = {}) => {
  const onSelect = vi.fn();
  const onSortChange = vi.fn();
  const onToggle = vi.fn();
  render(
    <TriageRail
      hotspots={data} sort="alert" onSortChange={onSortChange}
      selectedId={null} onSelect={onSelect} open onToggle={onToggle} {...over}
    />,
  );
  return { onSelect, onSortChange, onToggle };
};

// The sort control is a native <select> whose <option> children also expose
// role="option"; scope option queries to the listbox so the sort choices do
// not pollute "one option per hotspot" assertions.
const listbox = () => screen.getByRole("listbox", { name: viLocale["triage.title"] });
const options = () => within(listbox()).getAllByRole("option");

describe("TriageRail", () => {
  it("renders one option per hotspot inside a listbox", () => {
    renderRail();
    expect(listbox()).toBeTruthy();
    expect(options()).toHaveLength(2);
  });

  it("falls back to '#id' when a hotspot has no name", () => {
    renderRail();
    expect(screen.getByText("Kyiv, Ukraine")).toBeTruthy();
    expect(screen.getByText("#2")).toBeTruthy();
  });

  it("marks the selected row via aria-selected", () => {
    renderRail({ selectedId: 1 });
    const opts = options();
    expect(opts[0].getAttribute("aria-selected")).toBe("true");
    expect(opts[1].getAttribute("aria-selected")).toBe("false");
  });

  it("calls onSelect with the whole hotspot, not just the id", () => {
    // page.tsx needs lat/lon to fly the map; an id would force a lookup.
    const { onSelect } = renderRail();
    fireEvent.click(options()[0]);
    expect(onSelect).toHaveBeenCalledWith(data[0]);
  });

  it("selects a row on Enter and on Space", () => {
    const { onSelect } = renderRail();
    fireEvent.keyDown(options()[1], { key: "Enter" });
    fireEvent.keyDown(options()[1], { key: " " });
    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it("reports sort changes", () => {
    const { onSortChange } = renderRail();
    fireEvent.change(screen.getByLabelText(viLocale["triage.sortBy"]), { target: { value: "conf" } });
    expect(onSortChange).toHaveBeenCalledWith("conf");
  });

  it("shows an empty message rather than a bare list", () => {
    renderRail({ hotspots: [] });
    expect(screen.getByText(viLocale["triage.empty"])).toBeTruthy();
  });

  it("collapses to a toggle that still reports the count", () => {
    renderRail({ open: false });
    expect(screen.queryByRole("listbox")).toBeNull();
    const toggle = screen.getByRole("button", { name: viLocale["triage.expand"] });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("reports toggle clicks", () => {
    const { onToggle } = renderRail();
    fireEvent.click(screen.getByRole("button", { name: viLocale["triage.collapse"] }));
    expect(onToggle).toHaveBeenCalled();
  });
});
