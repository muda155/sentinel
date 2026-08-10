import { describe, expect, it } from "vitest";
import { toCsv, toJson, toMarkdown, type ExportPayload } from "@/lib/export";
import type { CompareRow } from "@/lib/compare";

const rows: CompareRow[] = [
  { key: "conf", labelKey: "compare.confidence", a: 78.5, b: 87.3, delta: 8.8, direction: "up", trusted: true },
  { key: "tone", labelKey: "compare.meanTone", a: null, b: -3, delta: null, direction: "none", trusted: true },
];

const payload: ExportPayload = {
  hotspot: "Khartoum Region",
  windowA: { from: "2026-08-03T14:00:00Z", to: "2026-08-04T14:00:00Z" },
  windowB: { from: "2026-08-04T14:00:00Z", to: "2026-08-05T14:00:00Z" },
  rows,
  citations: [{ index: 1, title: "Clashes reported", url: "https://x.test/a", domain: "x.test" }],
};

describe("toCsv", () => {
  it("emits a header and one row per metric", () => {
    const lines = toCsv(rows).trim().split("\n");
    expect(lines[0]).toBe("metric,window_a,window_b,delta,direction,trusted");
    expect(lines[1]).toBe("conf,78.5,87.3,8.8,up,true");
  });

  it("leaves absent values empty rather than writing null", () => {
    expect(toCsv(rows).trim().split("\n")[2]).toBe("tone,,-3,,none,true");
  });

  it("quotes a metric name containing a comma", () => {
    const csv = toCsv([{ ...rows[0], key: "a,b" }]);
    expect(csv).toContain('"a,b"');
  });
});

describe("toJson", () => {
  it("round-trips the payload", () => {
    const parsed = JSON.parse(toJson(payload));
    expect(parsed.hotspot).toBe("Khartoum Region");
    expect(parsed.rows).toHaveLength(2);
    expect(parsed.windowA.from).toBe("2026-08-03T14:00:00Z");
  });
});

describe("toMarkdown", () => {
  it("titles the report and states both windows", () => {
    const md = toMarkdown(payload, null);
    expect(md).toContain("# Khartoum Region");
    expect(md).toContain("2026-08-03T14:00:00Z");
    expect(md).toContain("2026-08-04T14:00:00Z");
  });

  it("renders the metric table", () => {
    expect(toMarkdown(payload, null)).toContain("| conf | 78.5 | 87.3 | +8.8 |");
  });

  it("includes the narrative and numbered sources when present", () => {
    const md = toMarkdown(payload, "Fighting intensified [1].");
    expect(md).toContain("Fighting intensified [1].");
    expect(md).toContain("[1] Clashes reported — https://x.test/a");
  });

  it("says so when no narrative was generated", () => {
    expect(toMarkdown(payload, null)).toContain("No narrative report was generated");
  });

  it("renders a URL-less citation without a dangling em dash", () => {
    const md = toMarkdown(
      { ...payload, citations: [{ index: 2, title: "Unlinked report", url: null, domain: "" }] },
      null,
    );
    expect(md).toContain("[2] Unlinked report");
    expect(md).not.toContain("Unlinked report —");
  });
});
