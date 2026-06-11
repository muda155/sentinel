import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", (url: string) => {
    calls.push(url);
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
  return calls;
}

describe("api client", () => {
  it("search() URL-encodes the query", async () => {
    const calls = stubFetch();
    await api.search("drone strike & raid", "tok");
    expect(calls[0]).toContain("/search?q=drone%20strike%20%26%20raid");
  });
  it("hotspotEvents() targets the hotspot events path", async () => {
    const calls = stubFetch();
    await api.hotspotEvents(42, "tok");
    expect(calls[0]).toContain("/hotspots/42/events");
  });
});
