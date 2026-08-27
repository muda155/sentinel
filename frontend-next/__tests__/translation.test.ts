import { describe, it, expect } from "vitest";
import { anyClaimTranslated, shouldTranslate, displaySummary, displayClaimText } from "@/lib/translation";
import type { Claim } from "@/lib/api";
import type { Translation } from "@/lib/api";

const claim = (id: number, text: string): Claim => ({
  claim_id: id, claim_text: text, status: "corroborated", evidence: [],
});

const tr: Translation = {
  lang: "vi", summary: "Lực lượng đã tiến lên [1].", summary_translated: true,
  claims: [{ claim_id: 7, text: "Quân đội tiến về phía bắc." }], cached: false,
};

describe("shouldTranslate", () => {
  it("is false for the English locale", () => {
    expect(shouldTranslate("en", "Forces advanced [1].", [claim(7, "x")])).toBe(false);
  });
  it("is false when there is nothing to translate", () => {
    expect(shouldTranslate("vi", "", [])).toBe(false);
    expect(shouldTranslate("vi", undefined, undefined)).toBe(false);
  });
  it("is true for vi with a summary or with claims", () => {
    expect(shouldTranslate("vi", "Forces advanced [1].", [])).toBe(true);
    expect(shouldTranslate("vi", "", [claim(7, "x")])).toBe(true);
  });
});

describe("displaySummary", () => {
  it("returns English when there is no translation", () => {
    expect(displaySummary("Forces advanced [1].", null, false))
      .toBe("Forces advanced [1].");
  });
  it("returns English when the reader asked for the original", () => {
    expect(displaySummary("Forces advanced [1].", tr, true))
      .toBe("Forces advanced [1].");
  });
  it("returns English when the server could not translate it safely", () => {
    const untranslated = { ...tr, summary_translated: false };
    expect(displaySummary("Forces advanced [1].", untranslated, false))
      .toBe("Forces advanced [1].");
  });
  it("returns the translation and preserves citation markers", () => {
    const out = displaySummary("Forces advanced [1].", tr, false);
    expect(out).toBe("Lực lượng đã tiến lên [1].");
    expect(out).toContain("[1]");
  });
});

describe("displayClaimText", () => {
  it("falls back to English for a claim the translation omitted", () => {
    expect(displayClaimText(claim(99, "Unrelated claim."), tr, false))
      .toBe("Unrelated claim.");
  });
  it("returns the translated text when present", () => {
    expect(displayClaimText(claim(7, "Military forces advanced north."), tr, false))
      .toBe("Quân đội tiến về phía bắc.");
  });
  it("returns English when the reader asked for the original", () => {
    expect(displayClaimText(claim(7, "Military forces advanced north."), tr, true))
      .toBe("Military forces advanced north.");
  });
});

describe("anyClaimTranslated", () => {
  it("is false without a translation", () => {
    expect(anyClaimTranslated([claim(7, "Military forces advanced north.")], null))
      .toBe(false);
  });
  it("is true when a claim reads back in Vietnamese", () => {
    expect(anyClaimTranslated([claim(7, "Military forces advanced north.")], tr))
      .toBe(true);
  });
  it("is false when the endpoint returned the English source unchanged", () => {
    // an over-budget claim is never sent, and its fallback is the same string -
    // nothing was translated, so no disclosure is owed
    const english: Translation = {
      ...tr, claims: [{ claim_id: 7, text: "Military forces advanced north." }],
    };
    expect(anyClaimTranslated([claim(7, "Military forces advanced north.")], english))
      .toBe(false);
  });
});
