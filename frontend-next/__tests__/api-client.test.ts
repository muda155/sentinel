import { describe, it, expect, vi, afterEach } from "vitest";
import { api, ApiError } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", (url: string) => {
    calls.push(url);
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
  return calls;
}

function stubFetchStatus(status: number) {
  vi.stubGlobal("fetch", () =>
    Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve({}) }));
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
  it("throws ApiError carrying the HTTP status on a non-2xx response", async () => {
    stubFetchStatus(409);
    const err = await api.createUser({ username: "x", password: "password123", role: "analyst" }, "tok")
      .then(() => null)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });
  it("throws ApiError(401) when the token is rejected", async () => {
    stubFetchStatus(401);
    const err = await api.users("tok").then(() => null).catch((e: unknown) => e);
    expect((err as ApiError).status).toBe(401);
  });
});
