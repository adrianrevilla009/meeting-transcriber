import { ApiError, auth } from "./api";
import type { AssistantEvent, AssistantStatus } from "./types";

/** El asistente (módulo 3) se sirve bajo /assistant para evitar CORS, igual que la API bajo /api. */
const BASE = "/assistant/v1";

/** Códigos con los que la UI debe decir "Asistente no disponible" en lugar de un error técnico. */
export function isUnavailable(e: unknown): boolean {
  return e instanceof ApiError && [0, 404, 502, 503, 504].includes(e.status);
}

const UNAVAILABLE = "Asistente no disponible";

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("Authorization", `Bearer ${auth.get()}`);
  return headers;
}

async function failFrom(res: Response): Promise<never> {
  if (res.status === 401) {
    window.dispatchEvent(new Event("mt:unauthorized"));
    throw new ApiError(401, "Token inválido");
  }
  if ([404, 502, 503, 504].includes(res.status)) throw new ApiError(res.status, UNAVAILABLE);
  let msg = res.statusText || `Error ${res.status}`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") msg = body.detail;
    else if (typeof body.error === "string") msg = body.error;
  } catch {
    /* cuerpo no JSON */
  }
  throw new ApiError(res.status, msg);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = authHeaders(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, UNAVAILABLE);
  }
  if (!res.ok) return failFrom(res);
  const text = await res.text();
  if (!text) return undefined as T;
  return ((res.headers.get("content-type") ?? "").includes("application/json") ? JSON.parse(text) : text) as T;
}

export const assistant = {
  follow: (id: number) =>
    request<{ meeting_id: number; following: boolean }>(`/meetings/${id}/follow`, { method: "POST", body: "{}" }),
  unfollow: (id: number) => request<void>(`/meetings/${id}/follow`, { method: "DELETE" }),
  status: (id: number) => request<AssistantStatus>(`/meetings/${id}/status`),
  ask: (id: number, text: string) =>
    request<{ question_id: string }>(`/meetings/${id}/ask`, { method: "POST", body: JSON.stringify({ text }) }),
  answer: (id: number, questionId: string) =>
    request<void>(`/meetings/${id}/questions/${encodeURIComponent(questionId)}/answer`, { method: "POST" }),
};

/**
 * Parser incremental de Server-Sent Events: recibe trozos de texto (que pueden cortar un evento por la mitad)
 * y devuelve los `data:` completos. Ignora comentarios (líneas que empiezan por ":", usadas como latido).
 */
export class SseParser {
  private buffer = "";

  push(chunk: string): string[] {
    // Se normaliza todo el búfer: un \r\n puede llegar partido entre dos trozos.
    this.buffer = (this.buffer + chunk).replace(/\r\n/g, "\n");
    const out: string[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) out.push(data);
      end = this.buffer.indexOf("\n\n");
    }
    return out;
  }
}

export interface StreamOptions {
  /** Espera inicial antes de reconectar (crece hasta `maxRetryMs`). */
  retryMs?: number;
  maxRetryMs?: number;
  /** Informa de si la conexión está viva o reintentando. */
  onConnection?: (state: "open" | "retrying") => void;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(done, ms);
    function done() {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });
}

/**
 * Sigue el flujo de eventos de una reunión con fetch + ReadableStream (EventSource no admite la cabecera
 * Authorization). Si se corta, reconecta pidiendo solo lo posterior al último evento recibido. Termina al abortar
 * `signal`; lanza ante un token inválido o una reunión desconocida (errores que reintentar no arregla).
 */
export async function streamEvents(
  meetingId: number,
  after: number,
  onEvent: (e: AssistantEvent) => void,
  signal: AbortSignal,
  { retryMs = 1500, maxRetryMs = 10_000, onConnection }: StreamOptions = {},
): Promise<void> {
  let last = after;
  let wait = retryMs;
  while (!signal.aborted) {
    try {
      const res = await fetch(`${BASE}/meetings/${meetingId}/events?after=${last}`, {
        headers: authHeaders({ Accept: "text/event-stream" }),
        signal,
      });
      if (res.status === 401 || res.status === 404) await failFrom(res);
      if (!res.ok || !res.body) throw new ApiError(res.status, UNAVAILABLE);
      onConnection?.("open");
      wait = retryMs;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const data of parser.push(decoder.decode(value, { stream: true }))) {
          let event: AssistantEvent;
          try {
            event = JSON.parse(data) as AssistantEvent;
          } catch {
            continue; // un evento corrupto no debe tirar el flujo
          }
          if (signal.aborted) return;
          if (typeof event.id !== "number" || event.id <= last) continue; // duplicado tras reconectar
          last = event.id;
          onEvent(event);
        }
      }
    } catch (e) {
      if (signal.aborted) return;
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) throw e;
    }
    if (signal.aborted) return;
    onConnection?.("retrying");
    await sleep(wait, signal);
    wait = Math.min(wait * 2, maxRetryMs);
  }
}
