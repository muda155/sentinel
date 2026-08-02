import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";
import type { Claim, Hotspot, HotspotClaims, HotspotEvent, HotspotSummary } from "@/lib/api";

// token is mutable so a test can supersede an in-flight fetch (generation counter)
const authState = vi.hoisted(() => ({ token: "test-token" }));

vi.mock("@/lib/api", () => ({
  api: {
    summary: vi.fn(),
    hotspotEvents: vi.fn(),
    hotspotClaims: vi.fn(),
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ token: authState.token }),
}));

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return { useT: () => ({ t: (k: string) => dict[k as keyof typeof dict] ?? k }) };
});

vi.mock("@/components/TrustTierEditor", () => ({ default: () => null }));

import { api } from "@/lib/api";
import HotspotDetail from "@/components/HotspotDetail";

const hotspotFixture: Hotspot = {
  hotspot_id: 123, lat: 10.5, lon: 20.5, conf_score: 80, convergence_score: 55,
  alert_level: "Critical", event_count: 3, consistency_score: 70,
  name: "Test Hotspot", start_window: "2026-07-30T00:00:00Z",
  end_window: "2026-08-02T00:00:00Z", created_at: "2026-08-01T00:00:00Z",
};

const summaryFixture: HotspotSummary = {
  summary: "Conflict escalating near the border.",
  conflict_detected: true, sources_cited: ["example.com"], conf_score: 80, convergence_score: 55,
};

const eventFixture: HotspotEvent = {
  event_id: 1, title: "Clashes reported", url: "https://example.com/1", domain: "example.com",
  source_system: "GDELT", event_type_label: "military_conflict", event_date: "2026-08-01T00:00:00Z",
  goldstein_scale: -8, avg_tone: -5.25, num_sources: 12, fatalities: 3,
  trust_tier: 3, trust_score: 0.8, citation_index: 1,
};

const claimsFixture: HotspotClaims = { claims: [], insufficient_sources: true };

const claimFixture: Claim = {
  claim_id: 1, claim_text: "Claim A", status: "corroborated", evidence: [],
};

const summaryMock = vi.mocked(api.summary);
const eventsMock = vi.mocked(api.hotspotEvents);
const claimsMock = vi.mocked(api.hotspotClaims);

const renderPanel = () => render(<HotspotDetail hotspot={hotspotFixture} onClose={() => {}} />);

beforeEach(() => {
  vi.clearAllMocks();
  authState.token = "test-token";
});

describe("HotspotDetail data loading", () => {
  it("renders the SITREP and the source list when all three fetches resolve", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // regression: a shared generation counter invalidated every fetch but the
    // last synchronous caller, leaving the brief on loading forever
    await screen.findByText(summaryFixture.summary);
    await screen.findByText(eventFixture.title!);
    expect(screen.getByText(`${viLocale["detail.sources"]} (1)`)).toBeTruthy();
    expect(screen.queryByText(viLocale["detail.loading"])).toBeNull();
  });

  it("shows a summary error with retry while sources still render", async () => {
    summaryMock.mockRejectedValue(new Error("boom"));
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    await screen.findByText(viLocale["detail.error"]);
    expect(screen.getByText(viLocale["detail.retry"])).toBeTruthy();
    await screen.findByText(eventFixture.title!);
  });

  it("retry re-fetches only the failed summary, not the other resources", async () => {
    summaryMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();
    await screen.findByText(viLocale["detail.error"]);

    fireEvent.click(screen.getByText(viLocale["detail.retry"]));

    await screen.findByText(summaryFixture.summary);
    expect(summaryMock).toHaveBeenCalledTimes(2);
    expect(eventsMock).toHaveBeenCalledTimes(1);
    expect(claimsMock).toHaveBeenCalledTimes(1);
  });

  it("shows an events error with retry, then recovers on retry", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    await screen.findByText(viLocale["detail.error"]);
    expect(screen.getByText(viLocale["detail.retry"])).toBeTruthy();
    await screen.findByText(summaryFixture.summary);
    // per-resource isolation: the brief renders while the sources header hides its count
    expect(screen.queryByText(`${viLocale["detail.sources"]} (1)`)).toBeNull();

    fireEvent.click(screen.getByText(viLocale["detail.retry"]));

    await screen.findByText(eventFixture.title!);
    expect(screen.getByText(`${viLocale["detail.sources"]} (1)`)).toBeTruthy();
    expect(eventsMock).toHaveBeenCalledTimes(2);
    expect(summaryMock).toHaveBeenCalledTimes(1);
    expect(claimsMock).toHaveBeenCalledTimes(1);
  });

  // the three fetchers are structurally identical, so a copy/paste miss in any
  // generation guard must fail here — parameterize the stale-discard test over
  // the resource instead of duplicating it (the original bug was exactly that miss)
  it.each([
    {
      resource: "summary",
      mock: summaryMock,
      fresh: summaryFixture,
      stale: { ...summaryFixture, summary: "STALE summary" },
      freshText: summaryFixture.summary,
      staleText: "STALE summary",
    },
    {
      resource: "events",
      mock: eventsMock,
      fresh: [eventFixture],
      stale: [{ ...eventFixture, event_id: 2, title: "STALE event", citation_index: 2 }],
      freshText: eventFixture.title!,
      staleText: "STALE event",
    },
    {
      resource: "claims",
      mock: claimsMock,
      fresh: { claims: [claimFixture], insufficient_sources: false },
      stale: { claims: [{ ...claimFixture, claim_id: 2, claim_text: "STALE claim" }], insufficient_sources: false },
      freshText: claimFixture.claim_text,
      staleText: "STALE claim",
    },
  ])(
    "discards a stale $resource response that settles after a superseding fetch",
    async ({ mock, fresh, stale, freshText, staleText }: { mock: Mock; fresh: unknown; stale: unknown; freshText: string; staleText: string }) => {
      // fetch #1 for the resource under test stays pending until we settle it
      let resolveFirst!: (v: unknown) => void;
      mock.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));

      // the other two resources resolve normally on both generations
      summaryMock.mockResolvedValue(summaryFixture);
      eventsMock.mockResolvedValue([eventFixture]);
      claimsMock.mockResolvedValue(claimsFixture);

      const { rerender } = renderPanel();

      // A token change re-fires the mount effect on the same instance, so generation
      // 2 supersedes generation 1 while fetch #1 is still in flight.
      authState.token = "token-b";
      mock.mockResolvedValueOnce(fresh);
      rerender(<HotspotDetail hotspot={hotspotFixture} onClose={() => {}} />);

      // fresh (generation 2) applied
      await screen.findByText(freshText);

      // the stale (generation 1) response settles last; the guard must discard it
      await act(async () => { resolveFirst(stale); });
      expect(screen.queryByText(staleText)).toBeNull();
      expect(screen.getByText(freshText)).toBeTruthy();
    },
  );

  it("renders severity badges on a source row", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // scope to the source row: the header aggregate renders the same
    // "3 <fatalities>" text, so a bare getByText would find two elements
    const row = (await screen.findByText(eventFixture.title!)).closest("li")!;
    expect(within(row).getByText(`3 ${viLocale["detail.fatalities"]}`)).toBeTruthy();
    expect(within(row).getByText(`12 ${viLocale["detail.numSources"]}`)).toBeTruthy();
    expect(within(row).getByText("GDELT")).toBeTruthy();
  });

  it("shows the severity aggregate and lifespan in the header", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture, { ...eventFixture, event_id: 2, fatalities: 12, citation_index: 2 }]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // wait on the unique lifespan text (aggregate renders only once events load),
    // then assert the aggregate's max-fatalities: the per-event badge for event 2
    // renders the same "12 <fatalities>" text, so expect exactly two occurrences
    await screen.findByText(new RegExp(viLocale["detail.activeSince"]));
    expect(screen.getAllByText(new RegExp(`12 ${viLocale["detail.fatalities"]}`)).length).toBe(2);
    expect(screen.getByText(new RegExp(viLocale["detail.activeSince"]))).toBeTruthy();
  });
});
