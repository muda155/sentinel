import { describe, it, expect } from "vitest";
import { relativeAge, STATUS_COLOR, STATUS_LABEL } from "@/lib/stream-status";

describe("relativeAge", () => {
  it("reports whole seconds under a minute", () => {
    expect(relativeAge(0)).toBe("0s");
    expect(relativeAge(12_400)).toBe("12s");
    expect(relativeAge(59_999)).toBe("59s");
  });
  it("rolls up to minutes, hours, days", () => {
    expect(relativeAge(60_000)).toBe("1m");
    expect(relativeAge(59 * 60_000)).toBe("59m");
    expect(relativeAge(60 * 60_000)).toBe("1h");
    expect(relativeAge(23 * 3600_000)).toBe("23h");
    expect(relativeAge(24 * 3600_000)).toBe("1d");
  });
  it("clamps a negative age to zero rather than printing '-3s'", () => {
    // Clock skew between the browser and an event timestamp must not render
    // as a negative duration.
    expect(relativeAge(-3000)).toBe("0s");
  });
});

describe("status maps", () => {
  it("covers every status with a colour and an i18n key", () => {
    for (const s of ["connecting", "live", "reconnecting"] as const) {
      expect(STATUS_COLOR[s]).toMatch(/^#[0-9a-f]{6}$/i);
      expect(STATUS_LABEL[s]).toMatch(/^stream\./);
    }
  });
  it("does not reuse the FR-13 alert palette", async () => {
    // lib/colors.ts owns alert/confidence colour. A green dot that happens to
    // be the FR-13 "high confidence" green would imply a meaning it lacks.
    const colors = await import("@/lib/colors");
    const fr13 = Object.values(colors).filter((v) => typeof v === "string");
    for (const c of Object.values(STATUS_COLOR)) {
      expect(fr13).not.toContain(c);
    }
  });
});
