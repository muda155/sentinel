import { describe, it, expect } from "vitest";
import { parseCitations } from "@/lib/citations";

describe("parseCitations", () => {
  it("splits text and citation markers", () => {
    const parts = parseCitations("Forces advanced 5km [1]. Artillery deployed [2].");
    const cites = parts.filter((p) => p.type === "cite").map((p) => p.n);
    expect(cites).toEqual([1, 2]);
  });
  it("preserves surrounding text", () => {
    const parts = parseCitations("Hello [3] world");
    expect(parts[0]).toEqual({ type: "text", text: "Hello " });
    expect(parts[1]).toEqual({ type: "cite", n: 3 });
    expect(parts[2]).toEqual({ type: "text", text: " world" });
  });
});
