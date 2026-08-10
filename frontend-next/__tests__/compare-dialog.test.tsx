import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";
import type { Hotspot, HotspotEvent } from "@/lib/api";

const authState = vi.hoisted(() => ({ token: "test-token" }));

vi.mock("@/lib/api", () => ({ api: { report: vi.fn() } }));

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ token: authState.token }) }));

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => dict[k as keyof typeof dict] ?? k }) };
});

import { api } from "@/lib/api";
import CompareDialog from "@/components/CompareDialog";

const hotspot: Hotspot = {
  hotspot_id: 1, lat: 0, lon: 0, conf_score: 50, convergence_score: null,
  alert_level: "Medium", event_count: 2, name: "Khartoum Region",
  start_window: null, end_window: null, created_at: null,
};

const ev = (id: number, date: string): HotspotEvent => ({
  event_id: id, title: `E${id}`, url: null, domain: `d${id}.com`,
  source_system: "GDELT", event_type_label: "military_conflict", event_date: date,
  goldstein_scale: null, avg_tone: null, num_sources: null, fatalities: null,
  duplicate_count: 1, trust_tier: 1, trust_score: 0.5,
  country_code: "US", citation_index: id,
});

const events = [ev(1, "2026-08-05T06:00:00Z"), ev(2, "2026-08-04T06:00:00Z")];

describe("CompareDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("labels every figure as recomputed, not published", () => {
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={() => {}} />);
    expect(screen.getByText(viLocale["compare.recomputed"])).toBeTruthy();
  });

  it("renders one row per comparable metric", () => {
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={() => {}} />);
    expect(screen.getByText(viLocale["compare.events"])).toBeTruthy();
    expect(screen.getByText(viLocale["compare.confidence"])).toBeTruthy();
  });

  it("requests a narrative only when asked", async () => {
    (api.report as Mock).mockResolvedValue({
      narrative: "Fighting intensified [1].", citations: [], model: "m", cached: false,
    });
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={() => {}} />);
    expect(api.report).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(viLocale["compare.generate"]));
    await waitFor(() => expect(screen.getByText("Fighting intensified [1].")).toBeTruthy());
  });

  it("reports report failure without breaking the comparison", async () => {
    (api.report as Mock).mockRejectedValue(new Error("503"));
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={() => {}} />);
    fireEvent.click(screen.getByText(viLocale["compare.generate"]));
    await waitFor(() => expect(screen.getByText(viLocale["compare.reportUnavailable"])).toBeTruthy());
    expect(screen.getByText(viLocale["compare.exportCsv"])).toBeTruthy();
  });

  it("focuses the dialog and closes on Escape", () => {
    const onClose = vi.fn();
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={onClose} />);
    // The dialog takes focus on mount; otherwise a keydown handler on a div
    // with no tabIndex never sees the key the user actually presses.
    const dialog = screen.getByRole("dialog");
    expect(document.activeElement).toBe(dialog);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("clears a generated report when the duration changes", async () => {
    (api.report as Mock).mockResolvedValue({
      narrative: "Fighting intensified [1].", citations: [], model: "m", cached: false,
    });
    render(<CompareDialog hotspot={hotspot} events={events} claims={null} onClose={() => {}} />);
    fireEvent.click(screen.getByText(viLocale["compare.generate"]));
    await waitFor(() => expect(screen.getByText("Fighting intensified [1].")).toBeTruthy());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "7d" } });
    // The old window's narrative must not ship under the new window headers.
    expect(screen.queryByText("Fighting intensified [1].")).toBeNull();
  });
});
