import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { ToastProvider } from "../components/Toasts";
import { RecorderProvider } from "../recorder/RecorderContext";
import type { Meeting, MtEvent, Progress, Requirement, Segment } from "../types";

type Handler = unknown | ((req: { url: URL; init: RequestInit }) => unknown);
export interface Call {
  method: string;
  path: string;
  init: RequestInit;
}

/**
 * Sustituye fetch por un router en memoria: claves "GET /meetings" → cuerpo JSON (o función).
 * Devuelve las llamadas recibidas. Una ruta sin definir responde 404.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init.method ?? "GET").toUpperCase();
      const path = url.pathname.replace(/^\/api/, "");
      calls.push({ method, path: path + url.search, init });
      const key = [`${method} ${path}${url.search}`, `${method} ${path}`].find((k) => k in routes);
      if (!key) return new Response(JSON.stringify({ detail: "no mock" }), { status: 404, headers: { "content-type": "application/json" } });
      const h = routes[key];
      const body = typeof h === "function" ? await (h as (r: { url: URL; init: RequestInit }) => unknown)({ url, init }) : h;
      if (body instanceof Response) return body;
      if (body === undefined) return new Response(null, { status: 204 });
      if (typeof body === "string") return new Response(body, { status: 200, headers: { "content-type": "text/markdown" } });
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

export function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname + loc.search}</div>;
}

/** Renderiza con React Query (sin reintentos), toasts, grabadora y router en `route`. */
export function renderApp(ui: ReactElement, { route = "/", path = "/" }: { route?: string; path?: string } = {}) {
  localStorage.setItem("mt_token", "tok");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <RecorderProvider>
          <MemoryRouter initialEntries={[route]}>
            <Routes>
              <Route path={path} element={ui} />
              <Route path="*" element={<div>otra página</div>} />
            </Routes>
            <LocationProbe />
          </MemoryRouter>
        </RecorderProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

// ---------- Fábricas de datos ----------
const ISO = "2026-11-13T10:00:00Z";

export const meeting = (p: Partial<Meeting> = {}): Meeting => ({
  id: 1,
  title: "Kickoff",
  project: "pagos",
  status: "done",
  analysis_status: "done",
  analysis_error: null,
  created_at: ISO,
  finished_at: "2026-11-13T10:42:00Z",
  ...p,
});

export const progress = (p: Partial<Progress> = {}): Progress => ({
  chunks_total: 2,
  chunks_pending: 0,
  chunks_processing: 0,
  chunks_done: 2,
  chunks_failed: 0,
  segments: 3,
  events: 2,
  ...p,
});

export const segment = (p: Partial<Segment> = {}): Segment => ({
  id: 1,
  source: "system",
  start: 0,
  end: 4,
  text: "Hola",
  avg_logprob: -0.2,
  low_confidence: false,
  ...p,
});

export const event = (p: Partial<MtEvent> = {}): MtEvent => ({
  id: 1,
  requirement_id: null,
  meeting_id: 1,
  segment_id: 1,
  kind: "decision",
  summary: "Algo decidido",
  quote: "una cita",
  timestamp: 0,
  created_at: ISO,
  ...p,
});

export const requirement = (p: Partial<Requirement> = {}): Requirement => ({
  id: 1,
  project: "pagos",
  title: "Método de pago",
  created_at: ISO,
  ...p,
});
