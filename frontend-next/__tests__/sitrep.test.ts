import { describe, it, expect } from "vitest";
import { sitrepState, LLM_THRESHOLD } from "@/lib/sitrep";

describe("sitrepState", () => {
  it("returns ready when summary text is present", () => {
    expect(sitrepState("Forces advanced [1].", 10)).toBe("ready");
    expect(sitrepState("Forces advanced [1].", 90)).toBe("ready");
  });

  it("returns pending when no summary but conf_score is above threshold", () => {
    expect(sitrepState("", 78.8)).toBe("pending");
    expect(sitrepState("   ", LLM_THRESHOLD + 0.1)).toBe("pending");
  });

  it("returns below_threshold when no summary and conf_score is at or below threshold", () => {
    expect(sitrepState("", LLM_THRESHOLD)).toBe("below_threshold");
    expect(sitrepState("", 12)).toBe("below_threshold");
  });
});
