import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Meeting } from "./Meeting";
import { event, meeting, mockApi, progress, renderApp, requirement, segment } from "../test/utils";
import type { Meeting as MeetingT } from "../types";

const SEGMENTS = [
  segment({ id: 1, source: "system", start: 0, text: "Buenos días a todos." }),
  segment({ id: 2, source: "system", start: 3, text: "Queremos pagar con Bizum." }),
  segment({ id: 3, source: "mic", start: 8, text: "Lo apunto, ¿y en dólares?", low_confidence: true }),
];
const EVENTS = [
  event({ id: 1, kind: "new_requirement", requirement_id: 7, segment_id: 2, timestamp: 3, summary: "Pago con Bizum", quote: "pagar con Bizum" }),
  event({ id: 2, kind: "open_question", segment_id: 3, timestamp: 8, summary: "¿Pagos en dólares?", quote: "y en dólares" }),
];

function setup(m: Partial<MeetingT> = {}, extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /meetings/1": meeting(m),
    "GET /meetings/1/progress": progress(),
    "GET /meetings/1/transcript": SEGMENTS,
    "GET /meetings/1/events": EVENTS,
    "GET /requirements": [requirement({ id: 7, title: "Método de pago" })],
    ...extra,
  });
}

const open = (route = "/meetings/1") => renderApp(<Meeting />, { route, path: "/meetings/:id" });

describe("Meeting page", () => {
  it("shows header, finished stepper and grouped AI insights with quotes", async () => {
    setup();
    open();
    expect(await screen.findByRole("heading", { name: "Kickoff" })).toBeInTheDocument();
    expect(screen.getByText("42 min", { exact: false })).toBeInTheDocument();
    expect(document.querySelectorAll(".step-done")).toHaveLength(4);

    const col = (await screen.findByText("Pago con Bizum")).closest(".insight-col") as HTMLElement;
    expect(within(col).getByText("Requisitos nuevos")).toBeInTheDocument();
    expect(within(col).getByText("Pago con Bizum")).toBeInTheDocument();
    expect(within(col).getByText("pagar con Bizum")).toBeInTheDocument();
    expect(within(col).getByRole("link", { name: "Método de pago" })).toHaveAttribute("href", "/requirements?focus=7");
    const questions = screen.getByText("Dudas abiertas").closest(".insight-col") as HTMLElement;
    expect(within(questions).getByText("¿Pagos en dólares?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Análisis IA/ })).toHaveTextContent("Análisis IA2");
  });

  it("jumps from an insight to its sentence in the transcript", async () => {
    setup();
    open();
    await userEvent.click(await screen.findByRole("button", { name: /00:03 · ver en la transcripción/ }));
    expect(screen.getByTestId("location")).toHaveTextContent("/meetings/1?seg=2");
    expect(await screen.findByText("Queremos pagar con Bizum.")).toBeInTheDocument();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("opens the transcript directly from a ?seg= link", async () => {
    setup();
    open("/meetings/1?seg=3");
    expect(await screen.findByText("Lo apunto, ¿y en dólares?")).toBeInTheDocument();
  });

  it("renders the transcript as a chat with speakers, timestamps and doubtful flags", async () => {
    setup();
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Transcripción/ }));
    const rows = document.querySelectorAll(".bubble-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveClass("from-system", "first");
    expect(rows[1]).not.toHaveClass("first"); // mismo hablante seguido: sin etiqueta
    expect(rows[2]).toHaveClass("from-mic", "first");
    expect(within(rows[2] as HTMLElement).getByText("Yo")).toBeInTheDocument();
    expect(rows[2].querySelector(".bubble")).toHaveClass("doubtful");
    expect(within(rows[1] as HTMLElement).getByText("00:03")).toBeInTheDocument();
  });

  it("filters the transcript by text and by doubtful sentences", async () => {
    setup();
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Transcripción/ }));
    await userEvent.type(screen.getByPlaceholderText("Buscar en esta reunión"), "bizum");
    expect(document.querySelectorAll(".bubble-row")).toHaveLength(1);
    expect(document.querySelector("mark")).toHaveTextContent("Bizum");
    await userEvent.clear(screen.getByPlaceholderText("Buscar en esta reunión"));
    await userEvent.click(screen.getByRole("button", { name: /1 dudosas/ }));
    expect(document.querySelectorAll(".bubble-row")).toHaveLength(1);
    expect(screen.getByText("Lo apunto, ¿y en dólares?")).toBeInTheDocument();
  });

  it("shows live transcription progress and skeletons while processing", async () => {
    setup({ status: "finished", analysis_status: "pending" }, { "GET /meetings/1/progress": progress({ chunks_total: 4, chunks_done: 1, segments: 2 }) });
    open();
    expect(await screen.findByText("1/4 · 2 frases")).toBeInTheDocument();
    expect(document.querySelector(".step-active")).toHaveTextContent("Transcripción");
    expect(screen.getByText(/El análisis empieza al terminar/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reanalizar/ })).toBeDisabled();
  });

  it("failed analysis shows the error and retries", async () => {
    const calls = setup({ analysis_status: "failed", analysis_error: "Ollama timeout" }, { "POST /meetings/1/analyze": meeting({ analysis_status: "pending" }) });
    open();
    expect(await screen.findByText("Ollama timeout")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/meetings/1/analyze")).toBe(true));
    expect(await screen.findByText("Reanálisis en cola")).toBeInTheDocument();
  });

  it("warns about chunks that failed to transcribe", async () => {
    setup({}, { "GET /meetings/1/progress": progress({ chunks_failed: 2 }) });
    open();
    expect(await screen.findByText(/2 fragmentos no se pudieron transcribir/)).toBeInTheDocument();
  });

  it("offers to close a meeting left open by a closed browser", async () => {
    const calls = setup({ status: "recording", finished_at: null }, { "POST /meetings/1/finish": meeting({ status: "finished" }) });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Cerrar y transcribir/ }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/meetings/1/finish")).toBe(true));
  });

  it("deletes only after confirming, then goes home", async () => {
    const calls = setup({}, { "DELETE /meetings/1": undefined });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Eliminar/ }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /Seguro/ }));
    await vi.waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/));
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/meetings/1"]);
  });

  it("downloads the markdown export with a safe file name", async () => {
    setup({ title: "Reunión: Diseño" }, { "GET /meetings/1/transcript?format=md": "# Reunión" });
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("reunion-diseno.md");
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Markdown/ }));
    await vi.waitFor(() => expect(click).toHaveBeenCalled());
  });

  it("shows a loading state instead of 'no findings' while events load", async () => {
    setup({}, { "GET /meetings/1/events": () => new Promise(() => undefined) });
    open();
    expect(await screen.findByText("Cargando el análisis…")).toBeInTheDocument();
    expect(screen.queryByText("Sin hallazgos")).not.toBeInTheDocument();
  });

  it("empty analysis after a finished meeting", async () => {
    setup({}, { "GET /meetings/1/events": [] });
    open();
    expect(await screen.findByText("Sin hallazgos")).toBeInTheDocument();
  });

  it("unknown meeting", async () => {
    mockApi({});
    open("/meetings/99");
    expect(await screen.findByText("Reunión no encontrada")).toBeInTheDocument();
  });
});
