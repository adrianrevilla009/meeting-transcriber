import type {
  Meeting,
  MtEvent,
  Progress,
  Requirement,
  RequirementHistory,
  SearchHit,
  Segment,
  SystemInfo,
} from "./types";

const BASE = "/api";
const TOKEN_KEY = "mt_token";

export const auth = {
  get(): string {
    try {
      return localStorage.getItem(TOKEN_KEY) ?? "";
    } catch {
      return "";
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* almacenamiento no disponible: el token vive solo en esta sesión */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nada que limpiar */
    }
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}, token = auth.get()): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "No se puede conectar con la API. ¿Está arrancada (make start)?");
  }
  if (res.status === 401) {
    window.dispatchEvent(new Event("mt:unauthorized"));
    throw new ApiError(401, "Token inválido");
  }
  if (!res.ok) {
    let msg = res.statusText || `Error ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* cuerpo no JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  check: (token: string) => request<Meeting[]>("/meetings", {}, token),
  system: () => request<SystemInfo>("/system"),

  meetings: () => request<Meeting[]>("/meetings"),
  meeting: (id: number) => request<Meeting>(`/meetings/${id}`),
  progress: (id: number) => request<Progress>(`/meetings/${id}/progress`),
  createMeeting: (title: string, project: string) => post<Meeting>("/meetings", { title, project }),
  uploadChunk: (id: number, form: FormData) =>
    request<unknown>(`/meetings/${id}/chunks`, { method: "POST", body: form }),
  finish: (id: number) => post<Meeting>(`/meetings/${id}/finish`),
  reanalyze: (id: number) => post<Meeting>(`/meetings/${id}/analyze`),
  deleteMeeting: (id: number) => request<void>(`/meetings/${id}`, { method: "DELETE" }),

  segments: (id: number) => request<Segment[]>(`/meetings/${id}/transcript?format=json`),
  markdown: (id: number) => request<string>(`/meetings/${id}/transcript?format=md`),
  events: (id: number) => request<MtEvent[]>(`/meetings/${id}/events`),

  requirements: (project?: string) =>
    request<Requirement[]>(`/requirements${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  history: (id: number) => request<RequirementHistory>(`/requirements/${id}/history`),
  search: (q: string) => request<SearchHit[]>(`/search?q=${encodeURIComponent(q)}&limit=100`),
};
