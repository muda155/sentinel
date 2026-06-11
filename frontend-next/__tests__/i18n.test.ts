import { describe, it, expect } from "vitest";
import { en } from "@/lib/locales/en";
import { vi as viDict } from "@/lib/locales/vi";
import { makeT, DEFAULT_LOCALE } from "@/lib/i18n-core";

describe("i18n dictionaries", () => {
  it("vi declares every en key", () => {
    expect(Object.keys(viDict).sort()).toEqual(Object.keys(en).sort());
  });
  it("default locale is Vietnamese", () => {
    expect(DEFAULT_LOCALE).toBe("vi");
  });
  it("t resolves keys per locale and falls back to the key", () => {
    expect(makeT("en")("detail.sources")).toBe("Sources");
    expect(makeT("vi")("detail.sources")).toBe("Nguồn tin");
    expect(makeT("vi")("nope.missing" as never)).toBe("nope.missing");
  });
});
