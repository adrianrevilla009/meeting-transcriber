import { describe, expect, it, vi } from "vitest";
import { api, ApiError, auth } from "./api";
import { mockApi } from "./test/utils";

describe("api client", () => {
  it("sends the bearer token under /api", async () => {
    auth.set("secreto");
    const calls = mockApi({ "GET /meetings": [] });
    await api.meetings();
    expect(calls[0].path).toBe("/meetings");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer secreto");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/meetings");
  });

  it("check() uses the given token, not the stored one", async () => {
    auth.set("viejo");
    const calls = mockApi({ "GET /meetings": [] });
    await api.check("nuevo");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer nuevo");
  });

  it("sends JSON bodies with content type", async () => {
    const calls = mockApi({ "POST /meetings": { id: 3 } });
    await api.createMeeting("T", "p");
    expect(new Headers(calls[0].init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ title: "T", project: "p" });
  });

  it("does not set JSON content type for uploads", async () => {
    const calls = mockApi({ "POST /meetings/1/chunks": {} });
    await api.uploadChunk(1, new FormData());
    expect(new Headers(calls[0].init.headers).get("Content-Type")).toBeNull();
  });

  it("encodes query parameters", async () => {
    const calls = mockApi({ "GET /search": [] });
    await api.search("pago & cobro");
    expect(calls.map((c) => c.path)).toEqual(["/search?q=pago%20%26%20cobro&limit=100"]);
  });

  it("401 broadcasts mt:unauthorized", async () => {
    mockApi({ "GET /meetings": new Response("{}", { status: 401 }) });
    const listener = vi.fn();
    window.addEventListener("mt:unauthorized", listener);
    await expect(api.meetings()).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("mt:unauthorized", listener);
  });

  it("surfaces FastAPI error details", async () => {
    mockApi({
      "POST /meetings/1/analyze": new Response(JSON.stringify({ detail: "La reunión sigue en curso" }), {
        status: 409,
      }),
    });
    const err = await api.reanalyze(1).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, message: "La reunión sigue en curso" });
  });

  it("translates network failures into a helpful message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.meetings()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("make start") });
  });

  it("returns text for markdown and undefined for 204", async () => {
    mockApi({ "GET /meetings/1/transcript": "# Hola", "DELETE /meetings/1": undefined });
    await expect(api.markdown(1)).resolves.toBe("# Hola");
    await expect(api.deleteMeeting(1)).resolves.toBeUndefined();
  });

  it("auth survives storage errors", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    expect(auth.get()).toBe("");
  });
});
