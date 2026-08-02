import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Hotspot, HotspotClaims, HotspotEvent, HotspotSummary } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    summary: vi.fn(),
    hotspotEvents: vi.fn(),
    hotspotClaims: vi.fn(),
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ token: "test-token" }),
}));

vi.mock("@/lib/i18n", async () => {
  const { vi } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => vi[k as keyof typeof vi] ?? k }) };
});

vi.mock("@/components/TrustTierEditor", () => ({ default: () => null }));

import { api } from "@/lib/api";
import HotspotDetail from "@/components/HotspotDetail";

const hotspotFixture: Hotspot = {
  hotspot_id: 123, lat: 10.5, lon: 20.5, conf_score: 80, convergence_score: 55,
  alert_level: "Critical", event_count: 3, consistency_score: 70,
  name: "Test Hotspot", end_window: "2026-08-02T00:00:00Z", created_at: "2026-08-01T00:00:00Z",
};

const summaryFixture: HotspotSummary = {
  summary: "Conflict escalating near the border.",
  conflict_detected: true, sources_cited: ["example.com"], conf_score: 80, convergence_score: 55,
};

const eventFixture: HotspotEvent = {
  event_id: 1, title: "Clashes reported", url: "https://example.com/1", domain: "example.com",
  source_system: "GDELT", event_type_label: "military_conflict", event_date: "2026-08-01T00:00:00Z",
  trust_tier: 3, trust_score: 0.8, citation_index: 1,
};

const claimsFixture: HotspotClaims = { claims: [], insufficient_sources: true };

const summaryMock = vi.mocked(api.summary);
const eventsMock = vi.mocked(api.hotspotEvents);
const claimsMock = vi.mocked(api.hotspotClaims);

const renderPanel = () => render(<HotspotDetail hotspot={hotspotFixture} onClose={() => {}} />);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("HotspotDetail data loading", () => {
  it("renders the SITREP and the source list when all three fetches resolve", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // regression: a shared generation counter invalidated every fetch but the
    // last synchronous caller, leaving the brief on "Đang tải…" forever
    await screen.findByText(summaryFixture.summary);
    await screen.findByText(eventFixture.title!);
    expect(screen.getByText("Nguồn tin (1)")).toBeTruthy();
    expect(screen.queryByText("Đang tải…")).toBeNull();
  });

  it("shows a summary error with retry while sources still render", async () => {
    summaryMock.mockRejectedValue(new Error("boom"));
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    await screen.findByText("Không tải được dữ liệu.");
    expect(screen.getByText("Thử lại")).toBeTruthy();
    await screen.findByText(eventFixture.title!);
  });

  it("retry re-fetches only the failed summary, not the other resources", async () => {
    summaryMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();
    await screen.findByText("Không tải được dữ liệu.");

    fireEvent.click(screen.getByText("Thử lại"));

    await screen.findByText(summaryFixture.summary);
    expect(summaryMock).toHaveBeenCalledTimes(2);
    expect(eventsMock).toHaveBeenCalledTimes(1);
    expect(claimsMock).toHaveBeenCalledTimes(1);
  });
});
