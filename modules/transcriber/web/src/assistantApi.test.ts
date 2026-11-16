import { describe, expect, it, vi } from "vitest";
import { ApiError, auth } from "./api";
import { assistant, isUnavailable, SseParser, streamEvents } from "./assistantApi";
import { mockApi } from "./test/utils";
import type { AssistantEvent } from "./types";

const enc = new TextEncoder();

/** Respuesta SSE cuyo cuerpo llega en los trozos indicados y luego se cierra. */
function sse(parts: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const p of parts) c.enqueue(enc.encode(p));
      c.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

const ev = (e: object) => `data: ${JSON.stringify(e)}\n\n`;
const status = (id: number) => ({ id, type: "status", state: "following" });
const question = (id: number, qid = "q1") => ({
  id,
  type: "question",
  question_id: qid,
  text: "¿Cuándo entregáis?",
  ts: 12,
  origin: "detected",
  score: 0.9,
});

const FAST = { retryMs: 1, maxRetryMs: 2 };

/** Ejecuta streamEvents hasta recibir `count` eventos y entonces aborta. */
async function collect(
  count: number,
  after = 0,
  options: Parameters<typeof streamEvents>[4] = FAST,
): Promise<AssistantEvent[]> {
  const ctl = new AbortController();
  const got: AssistantEvent[] = [];
  await streamEvents(
    1,
    after,
    (e) => {
      got.push(e);
      if (got.length === count) ctl.abort();
    },
    ctl.signal,
    options,
  );
  return got;
}

describe("SseParser", () => {
  it("joins events that arrive split across chunks", () => {
    const p = new SseParser();
    expect(p.push('data: {"a"')).toEqual([]);
    expect(p.push(":1}\n")).toEqual([]);
    expect(p.push("\ndata: x\n\n")).toEqual(['{"a":1}', "x"]);
  });

  it("accepts CRLF even when the pair is split between chunks", () => {
    const p = new SseParser();
    expect(p.push("data: a\r")).toEqual([]);
    expect(p.push("\n\r\ndata:b\r\n\r\n")).toEqual(["a", "b"]);
  });

  it("ignores comments (heartbeats) and joins multi-line data", () => {
    const p = new SseParser();
    expect(p.push(": ping\n\n")).toEqual([]);
    expect(p.push("data: a\ndata: b\n\n")).toEqual(["a\nb"]);
  });
});

describe("streamEvents", () => {
  it("delivers each event once and in order, whatever the chunking", async () => {
    auth.set("tok");
    const first = ev(status(1));
    const second = ev(question(2));
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValue(sse([first.slice(0, 15), first.slice(15) + second.slice(0, 30), second.slice(30)]));
    vi.stubGlobal("fetch", fetchMock);

    const got = await collect(2);

    expect(got.map((e) => e.id)).toEqual([1, 2]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/assistant/v1/meetings/1/events?after=0");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("reconnects asking only for what is newer than the last event and drops repeats", async () => {
    auth.set("tok");
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(sse([ev(question(3))]));
    fetchMock.mockResolvedValueOnce(sse([ev(question(3)), ev(question(4, "q2"))]));
    vi.stubGlobal("fetch", fetchMock);

    const got = await collect(2);

    expect(got.map((e) => e.id)).toEqual([3, 4]);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/assistant/v1/meetings/1/events?after=0",
      "/assistant/v1/meetings/1/events?after=3",
    ]);
  });

  it("starts after the given event id", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValue(sse([ev(question(8))]));
    vi.stubGlobal("fetch", fetchMock);
    await collect(1, 7);
    expect(fetchMock.mock.calls[0][0]).toBe("/assistant/v1/meetings/1/events?after=7");
  });

  it("retries after a gateway error and reports the connection state", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(new Response("bad gateway", { status: 502 }));
    fetchMock.mockResolvedValueOnce(sse([ev(status(1))]));
    vi.stubGlobal("fetch", fetchMock);
    const states: string[] = [];

    const got = await collect(1, 0, { ...FAST, onConnection: (s) => states.push(s) });

    expect(got).toHaveLength(1);
    expect(states).toEqual(["retrying", "open"]);
  });

  it("retries after a network error", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    fetchMock.mockResolvedValueOnce(sse([ev(status(1))]));
    vi.stubGlobal("fetch", fetchMock);
    expect(await collect(1)).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("skips corrupt events without dropping the stream", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse(["data: {no es json}\n\n", ev(status(5))])));
    const got = await collect(1);
    expect(got.map((e) => e.id)).toEqual([5]);
  });

  it("fails on an invalid token and notifies the app", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const onUnauthorized = vi.fn();
    window.addEventListener("mt:unauthorized", onUnauthorized);
    await expect(collect(1)).rejects.toMatchObject({ status: 401 });
    window.removeEventListener("mt:unauthorized", onUnauthorized);
    expect(onUnauthorized).toHaveBeenCalled();
  });

  it("fails on an unknown meeting instead of retrying forever", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(collect(1)).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does nothing when it is already aborted", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const ctl = new AbortController();
    ctl.abort();
    await streamEvents(1, 0, () => undefined, ctl.signal, FAST);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("assistant requests", () => {
  it("follow posts an empty JSON body with the bearer token under /assistant", async () => {
    auth.set("tok");
    const calls = mockApi({ "POST /assistant/v1/meetings/5/follow": { meeting_id: 5, following: true } });
    expect(await assistant.follow(5)).toEqual({ meeting_id: 5, following: true });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/assistant/v1/meetings/5/follow");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer tok");
    expect(calls[0].init.body).toBe("{}");
  });

  it("unfollow, status, ask and answer use the documented routes", async () => {
    const calls = mockApi({
      "DELETE /assistant/v1/meetings/5/follow": undefined,
      "GET /assistant/v1/meetings/5/status": { following: true, questions: 2, answers: 1 },
      "POST /assistant/v1/meetings/5/ask": { question_id: "q9" },
      "POST /assistant/v1/meetings/5/questions/q1/answer": {},
    });
    await expect(assistant.unfollow(5)).resolves.toBeUndefined();
    expect(await assistant.status(5)).toEqual({ following: true, questions: 2, answers: 1 });
    expect(await assistant.ask(5, "¿Qué riesgos hay?")).toEqual({ question_id: "q9" });
    await assistant.answer(5, "q1");
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "DELETE /assistant/v1/meetings/5/follow",
      "GET /assistant/v1/meetings/5/status",
      "POST /assistant/v1/meetings/5/ask",
      "POST /assistant/v1/meetings/5/questions/q1/answer",
    ]);
    expect(JSON.parse(calls[2].init.body as string)).toEqual({ text: "¿Qué riesgos hay?" });
  });

  it("treats a missing or down service as unavailable", async () => {
    mockApi({ "GET /assistant/v1/meetings/5/status": new Response("{}", { status: 503 }) });
    const down = await assistant.status(5).catch((e: unknown) => e);
    expect(down).toBeInstanceOf(ApiError);
    expect(isUnavailable(down)).toBe(true);

    mockApi({});
    expect(isUnavailable(await assistant.status(5).catch((e: unknown) => e))).toBe(true); // 404

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    const offline = await assistant.status(5).catch((e: unknown) => e);
    expect(offline).toMatchObject({ status: 0, message: "Asistente no disponible" });
    expect(isUnavailable(offline)).toBe(true);
  });

  it("does not hide other errors and reads their detail", async () => {
    mockApi({
      "POST /assistant/v1/meetings/5/ask": new Response(JSON.stringify({ detail: "Texto vacío" }), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
    });
    const err = await assistant.ask(5, "").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 422, message: "Texto vacío" });
    expect(isUnavailable(err)).toBe(false);
  });

  it("notifies the app on an invalid token", async () => {
    mockApi({ "GET /assistant/v1/meetings/5/status": new Response("{}", { status: 401 }) });
    const onUnauthorized = vi.fn();
    window.addEventListener("mt:unauthorized", onUnauthorized);
    await expect(assistant.status(5)).rejects.toMatchObject({ status: 401 });
    window.removeEventListener("mt:unauthorized", onUnauthorized);
    expect(onUnauthorized).toHaveBeenCalled();
  });
});
