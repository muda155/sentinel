import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { vi as viLocale } from "@/lib/locales/vi";
import type { Claim, Hotspot, HotspotClaims, HotspotEvent, HotspotSummary } from "@/lib/api";

// token is mutable so a test can supersede an in-flight fetch (generation counter)
const authState = vi.hoisted(() => ({ token: "test-token" }));
// locale is mutable so a test can turn the FR-30 translation fetch on/off
const i18nState = vi.hoisted(() => ({ locale: "en" as string }));

vi.mock("@/lib/api", () => ({
  api: {
    summary: vi.fn(),
    hotspotEvents: vi.fn(),
    hotspotClaims: vi.fn(),
    translation: vi.fn(),
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ token: authState.token }),
}));

vi.mock("@/lib/i18n", async () => {
  const { vi: dict } = await import("@/lib/locales/vi");
  return {
    useT: () => ({
      t: (k: string) => dict[k as keyof typeof dict] ?? k,
      locale: i18nState.locale,
    }),
  };
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
  trust_tier: 3, trust_score: 0.8, citation_index: 1, duplicate_count: 1,
};

const claimsFixture: HotspotClaims = { claims: [], insufficient_sources: true };

const claimFixture: Claim = {
  claim_id: 1, claim_text: "Claim A", status: "corroborated", evidence: [],
};

const summaryMock = vi.mocked(api.summary);
const eventsMock = vi.mocked(api.hotspotEvents);
const claimsMock = vi.mocked(api.hotspotClaims);
const translationMock = vi.mocked(api.translation);

const renderPanel = () => render(<HotspotDetail hotspot={hotspotFixture} onClose={() => {}} />);

beforeEach(() => {
  vi.clearAllMocks();
  authState.token = "test-token";
  i18nState.locale = "en";
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
    expect(screen.getByRole("button", { name: `${viLocale["detail.sources"]} (1)` })).toBeTruthy();
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
    expect(screen.queryByRole("button", { name: `${viLocale["detail.sources"]} (1)` })).toBeNull();

    fireEvent.click(screen.getByText(viLocale["detail.retry"]));

    await screen.findByText(eventFixture.title!);
    expect(screen.getByRole("button", { name: `${viLocale["detail.sources"]} (1)` })).toBeTruthy();
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
    eventsMock.mockResolvedValue([
      eventFixture,
      { ...eventFixture, event_id: 2, title: "ACLED Clashes", source_system: "ACLED", event_type_label: "armed_conflict",
        num_sources: null, fatalities: null, goldstein_scale: null, avg_tone: null, citation_index: 2 },
    ]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // scope to the source row: the header aggregate renders similar text
    const gdeltRow = (await screen.findByText(eventFixture.title!)).closest("li")!;
    expect(within(gdeltRow).getByText("GDELT")).toBeTruthy();
    expect(within(gdeltRow).getByText("military_conflict")).toBeTruthy();
    expect(within(gdeltRow).getByText(`3 ${viLocale["detail.fatalities"]}`)).toBeTruthy();
    expect(within(gdeltRow).getByText(`12 ${viLocale["detail.numSources"]}`)).toBeTruthy();

    // system/type badges only render when the hotspot's events differ in them;
    // num_sources <= 1 and null fatalities must not render a badge
    const acledRow = screen.getByText("ACLED").closest("li")!;
    expect(within(acledRow).getByText("armed_conflict")).toBeTruthy();
    expect(within(acledRow).queryByText(new RegExp(viLocale["detail.numSources"]))).toBeNull();
    expect(within(acledRow).queryByText(new RegExp(viLocale["detail.fatalities"]))).toBeNull();
  });

  it("renders the collapsed-reports badge when duplicate_count > 1", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    claimsMock.mockResolvedValue(claimsFixture);

    // GDELT emits one row per actor pair, so duplicate_count > 1 surfaces the
    // collapse as a leading badge with a localized tooltip
    eventsMock.mockResolvedValue([{ ...eventFixture, duplicate_count: 16 }]);
    renderPanel();
    await screen.findByText(eventFixture.title!);
    const row = screen.getByText(eventFixture.title!).closest("li")!;
    const badge = within(row).getByText(`16 ${viLocale["detail.reports"]}`);
    expect(badge.getAttribute("title")).toBe(
      viLocale["detail.reportsTooltip"].replace("{n}", "16"),
    );
  });

  it("omits the collapsed-reports badge when duplicate_count is 1", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    claimsMock.mockResolvedValue(claimsFixture);

    eventsMock.mockResolvedValue([eventFixture]);
    renderPanel();
    await screen.findByText(eventFixture.title!);
    const row = screen.getByText(eventFixture.title!).closest("li")!;
    expect(within(row).queryByText(new RegExp(viLocale["detail.reports"]))).toBeNull();
  });

  it("omits the collapsed-reports badge when duplicate_count is absent", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    claimsMock.mockResolvedValue(claimsFixture);

    // An API build predating the collapse omits the field entirely; the guard
    // must read undefined as "not collapsed" rather than throwing.
    const { duplicate_count: _omitted, ...withoutCount } = eventFixture;
    eventsMock.mockResolvedValue([withoutCount as HotspotEvent]);
    renderPanel();
    await screen.findByText(eventFixture.title!);
    const row = screen.getByText(eventFixture.title!).closest("li")!;
    expect(within(row).queryByText(new RegExp(viLocale["detail.reports"]))).toBeNull();
  });

  it("shows the severity aggregate and lifespan in the header", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture, { ...eventFixture, event_id: 2, fatalities: 12, citation_index: 2 }]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();

    // the aggregate labels the max as a max (not a total); both events are GDELT
    // so the per-row system/type badges are gated off and the text is unique
    await screen.findByText(new RegExp(viLocale["detail.activeSince"]));
    expect(screen.getByText(new RegExp(`12 ${viLocale["detail.maxFatalities"]}`))).toBeTruthy();
    expect(screen.getByText(new RegExp(viLocale["detail.activeSince"]))).toBeTruthy();
  });

  it("collapses the lifespan line when start and end fall on the same day", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    render(
      <HotspotDetail hotspot={{ ...hotspotFixture, start_window: "2026-08-02T00:00:00Z", end_window: "2026-08-02T00:00:00Z" }} onClose={() => {}} />
    );

    await screen.findByText(new RegExp(viLocale["detail.activeSince"]));
    expect(screen.getByText(new RegExp(viLocale["detail.activeSince"]))).toBeTruthy();
    expect(screen.queryByText(new RegExp(viLocale["detail.lastSeen"]))).toBeNull();
  });

  it("shows the activity sparkline only when events span more than one day", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    claimsMock.mockResolvedValue(claimsFixture);

    // all events on a single day -> sparkline hidden (inert chrome)
    eventsMock.mockResolvedValue([eventFixture]);
    renderPanel();
    await screen.findByText(eventFixture.title!);
    expect(screen.queryByText(viLocale["detail.section.activity"])).toBeNull();

    // events on two days -> sparkline renders with the translated aria-label
    eventsMock.mockResolvedValue([
      eventFixture,
      { ...eventFixture, event_id: 2, event_date: "2026-07-30T00:00:00Z", citation_index: 2 },
    ]);
    renderPanel();
    // wait for the second panel's events to resolve before asserting the sparkline
    const imgs = await screen.findAllByRole("img", { name: viLocale["detail.activity"] });
    expect(imgs.length).toBe(1);
    expect(screen.getAllByText(viLocale["detail.section.activity"]).length).toBe(1);
  });

  it("shows NLI probability next to a contradicting citation", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue({
      claims: [{
        claim_id: 1, claim_text: "Claim A", status: "disputed",
        evidence: [
          { event_id: 1, citation_index: 1, relation: "contradicts", probability: 0.91, domain: "example.com" },
          { event_id: 2, citation_index: 2, relation: "supports", probability: 0.5, domain: "example.org" },
        ],
      }],
      insufficient_sources: false,
    });

    renderPanel();

    await screen.findByText("Claim A");
    // the title tooltip carries probability on every citation...
    expect(screen.getByTitle(/0\.91/)).toBeTruthy();
    expect(screen.getByTitle(/0\.5/)).toBeTruthy();
    // ...but the inline p= is dispute-only (supporting is near-constant p≈1.00)
    expect(screen.getByText(/p=0\.91/)).toBeTruthy();
    expect(screen.queryByText(/p=0\.5/)).toBeNull();
  });

  it("draws the conf_score split when the inputs are present", async () => {
    // hotspot fixture with source_density 0.8, geopolitical_diversity 0.5,
    // conf_score 71 — see the existing renderPanel helper in this file.
    render(<HotspotDetail hotspot={{ ...hotspotFixture, source_density: 0.8, geopolitical_diversity: 0.5, conf_score: 71 }} onClose={() => {}} />);
    // the vi label contains literal parens, which are regex metacharacters —
    // escape them so the name regex matches the literal aria-label prefix
    const escaped = viLocale["detail.confidence"].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const bar = await screen.findByRole("img", { name: new RegExp(escaped) });
    expect(bar.getAttribute("aria-label")).toContain("56.0");
  });

  it("says not-yet-scored instead of drawing a bar when the inputs are null", async () => {
    // This fixture has neither conf inputs nor convergence inputs, so BOTH
    // score sections report not-yet-scored.
    render(<HotspotDetail hotspot={{ ...hotspotFixture, source_density: null, geopolitical_diversity: null }} onClose={() => {}} />);
    expect((await screen.findAllByText(viLocale["breakdown.unavailable"])).length).toBeGreaterThanOrEqual(1);
  });

  it("says not-yet-scored for a null convergence_score instead of a hollow bar", async () => {
    // conf is scored (bar) so the single "not-yet-scored" is the convergence
    // block's; a NULL convergence_score must not render a split bar or crash.
    render(<HotspotDetail hotspot={{ ...hotspotFixture, source_density: 0.8, geopolitical_diversity: 0.5, conf_score: 71, convergence_score: null, convergence_types: 3, convergence_events: 6 }} onClose={() => {}} />);
    expect(await screen.findByText(viLocale["breakdown.unavailable"])).toBeTruthy();
    expect(screen.getAllByText(viLocale["breakdown.unavailable"]).length).toBe(1);
    // the score line shows a dash rather than calling toFixed on null
    expect(screen.getByText("—")).toBeTruthy();
    // and no convergence bar is drawn (the vi label contains regex metachars)
    const escapedConv = viLocale["detail.convergence"].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    expect(screen.queryByRole("img", { name: new RegExp(escapedConv) })).toBeNull();
  });

  it("renders a single definition list whose dl elements carry dd definitions", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    render(<HotspotDetail hotspot={{ ...hotspotFixture, source_density: 0.8, geopolitical_diversity: 0.5, conf_score: 71 }} onClose={() => {}} />);
    // wait for the panel to render its score section
    await screen.findByText(/71\.0/);
    const dls = document.querySelectorAll("aside dl");
    expect(dls.length).toBeGreaterThan(0);
    dls.forEach((dl) => {
      expect(dl.querySelectorAll("dd").length).toBeGreaterThan(0);
    });
  });

  it("opens a collapsed Sources section when a citation jump targets it", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "Report claims escalation [1]." });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    renderPanel();
    await screen.findByText(eventFixture.title!);

    // Collapse Sources, then the SITREP [1] jump must reopen it (a collapsed
    // Section unmounts the <ol>, so the scroll would otherwise no-op).
    fireEvent.click(screen.getByRole("button", { name: `${viLocale["detail.sources"]} (1)` }));
    expect(screen.queryByText(eventFixture.title!)).toBeNull();

    fireEvent.click(screen.getByText("[1]"));
    await screen.findByText(eventFixture.title!);
  });

  it("does not request a translation for the English locale", async () => {
    summaryMock.mockResolvedValue(summaryFixture);
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);

    renderPanel();
    await screen.findByText(summaryFixture.summary);
    expect(translationMock).not.toHaveBeenCalled();
  });

  it("renders the Vietnamese summary and keeps the citation marker", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "Forces advanced [1]." });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    i18nState.locale = "vi";
    translationMock.mockResolvedValue({
      lang: "vi", summary: "Lực lượng đã tiến lên [1].", summary_translated: true,
      claims: [], cached: false,
    });

    renderPanel();

    // the translated text renders, the [1] superscript survives the display
    // path (FR-16 click-to-jump), and the disclosure line states the original
    // analysis is English
    await screen.findByText(/Lực lượng đã tiến lên/);
    expect(screen.getByText("[1]")).toBeTruthy();
    expect(screen.getByText(viLocale["detail.autoTranslated"])).toBeTruthy();
    expect(screen.getByText(viLocale["detail.showOriginal"])).toBeTruthy();
  });

  it("keeps the English summary when summary_translated is false", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "Forces advanced [1]." });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    i18nState.locale = "vi";
    translationMock.mockResolvedValue({
      lang: "vi", summary: "Lực lượng đã tiến lên [1].", summary_translated: false,
      claims: [], cached: false,
    });

    renderPanel();

    await screen.findByText(/Forces advanced/);
    expect(screen.queryByText(/Lực lượng đã tiến lên/)).toBeNull();
    // the disclosure only appears once the translation lands - wait for it
    await screen.findByText(viLocale["detail.translationUnavailable"]);
  });

  it("fires the translation fetch exactly once per panel open", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "Forces advanced [1]." });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    i18nState.locale = "vi";
    translationMock.mockResolvedValue({
      lang: "vi", summary: "Lực lượng đã tiến lên [1].", summary_translated: true,
      claims: [], cached: false,
    });

    renderPanel();
    await screen.findByText(/Lực lượng đã tiến lên/);

    // summary and claims settle in separate ticks; the effect must batch their
    // text in ONE call, or every panel open spends two rate-limit tokens
    expect(translationMock).toHaveBeenCalledTimes(1);
  });

  it("clears the translation when the locale switches back to English", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "Forces advanced [1]." });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue(claimsFixture);
    i18nState.locale = "vi";
    translationMock.mockResolvedValue({
      lang: "vi", summary: "Lực lượng đã tiến lên [1].", summary_translated: true,
      claims: [], cached: false,
    });

    const { rerender } = renderPanel();
    await screen.findByText(/Lực lượng đã tiến lên/);

    i18nState.locale = "en";
    rerender(<HotspotDetail hotspot={hotspotFixture} onClose={() => {}} />);

    // stale Vietnamese must not keep rendering once the locale is English
    await screen.findByText(/Forces advanced/);
    expect(screen.queryByText(/Lực lượng đã tiến lên/)).toBeNull();
    expect(screen.queryByText(viLocale["detail.autoTranslated"])).toBeNull();
  });

  it("discloses the translation on a hotspot with claims but no SITREP", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "" });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue({ claims: [claimFixture], insufficient_sources: false });
    i18nState.locale = "vi";
    translationMock.mockResolvedValue({
      lang: "vi", summary: "", summary_translated: true,
      claims: [{ claim_id: 1, text: "Khẳng định A" }], cached: false,
    });

    renderPanel();

    // there is no Brief to carry the disclosure, so it must appear under the
    // claims - translated text never ships without it, nor without the toggle
    await screen.findByText(/Khẳng định A/);
    expect(screen.getByText(viLocale["detail.autoTranslated"])).toBeTruthy();
    expect(screen.getByText(viLocale["detail.showOriginal"])).toBeTruthy();
  });

  it("shows no disclosure when every claim came back in English", async () => {
    summaryMock.mockResolvedValue({ ...summaryFixture, summary: "" });
    eventsMock.mockResolvedValue([eventFixture]);
    claimsMock.mockResolvedValue({ claims: [claimFixture], insufficient_sources: false });
    i18nState.locale = "vi";
    // the endpoint falls back to the English source for an over-budget claim
    translationMock.mockResolvedValue({
      lang: "vi", summary: "", summary_translated: true,
      claims: [{ claim_id: 1, text: claimFixture.claim_text }], cached: false,
    });

    renderPanel();

    await screen.findByText(/Claim A/);
    expect(screen.queryByText(viLocale["detail.autoTranslated"])).toBeNull();
  });
});
