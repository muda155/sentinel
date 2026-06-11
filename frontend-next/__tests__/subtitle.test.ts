import { describe, it, expect } from "vitest";
import { buildSubtitle } from "@/lib/subtitle";
import { makeT } from "@/lib/i18n-core";

const ev = (label: string) => ({ event_type_label: label });

describe("buildSubtitle", () => {
  it("joins distinct translated type labels with event count", () => {
    const t = makeT("vi");
    const s = buildSubtitle(
      [ev("armed_conflict"), ev("armed_conflict"), ev("military_conflict")], t,
    );
    expect(s).toBe("giao tranh vũ trang + xung đột quân sự — 3 sự kiện");
  });
  it("returns empty string for no events", () => {
    expect(buildSubtitle([], makeT("en"))).toBe("");
  });
});
