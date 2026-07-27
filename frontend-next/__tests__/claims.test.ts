import { describe, expect, it } from "vitest";
import { orderClaims, statusColor, statusLabelKey } from "@/lib/claims";
import type { Claim } from "@/lib/api";

const mk = (id: number, status: Claim["status"]): Claim => ({
  claim_id: id, claim_text: `c${id}`, status, evidence: [],
});

describe("claims helpers", () => {
  it("orders disputed first, corroborated second, single-source last", () => {
    const ordered = orderClaims([
      mk(1, "uncorroborated"), mk(2, "corroborated"), mk(3, "disputed"),
    ]);
    expect(ordered.map((c) => c.claim_id)).toEqual([3, 2, 1]);
  });

  it("maps status to color and i18n key", () => {
    expect(statusColor("disputed")).toBe("#f87171");
    expect(statusColor("corroborated")).toBe("#4ade80");
    expect(statusColor("uncorroborated")).toBe("#9ca3af");
    expect(statusLabelKey("disputed")).toBe("claims.disputed");
    expect(statusLabelKey("corroborated")).toBe("claims.corroborated");
    expect(statusLabelKey("uncorroborated")).toBe("claims.uncorroborated");
  });
});
