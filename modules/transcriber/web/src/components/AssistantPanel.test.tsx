import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssistantPanel } from "./AssistantPanel";
import { mockApi, renderApp } from "../test/utils";

const STATUS = "GET /assistant/v1/meetings/1/status";
const EVENTS = "GET /assistant/v1/meetings/1/events";
const FOLLOW = "/assistant/v1/meetings/1/follow";
const ANSWER = "/assistant/v1/meetings/1/questions/q1/answer";

/** Flujo SSE abierto: el test decide cuándo llega cada evento. */
function liveStream() {
  const enc = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: () => new Response(body, { headers: { "content-type": "text/event-stream" } }),
    send: (e: object) => controller.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`)),
  };
}

const question = (id: number, origin: "detected" | "manual" = "detected") => ({
  id,
  type: "question",
  question_id: "q1",
  text: "¿Cuándo entregáis?",
  ts: 75,
  origin,
  score: 0.9,
});

function setup(following: boolean, extra: Record<string, unknown> = {}) {
  const stream = liveStream();
  const calls = mockApi({
    [STATUS]: { following, questions: 0, answers: 0 },
    [EVENTS]: () => stream.response(),
    ...extra,
  });
  renderApp(<AssistantPanel meetingId={1} />);
  return { stream, calls };
}

describe("AssistantPanel", () => {
  it("shows the empty state and the privacy notice once the service answers", async () => {
    setup(false);
    expect(await screen.findByText("Sin preguntas todavía")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activar asistente" })).toBeInTheDocument();
    expect(screen.getByText(/filtro de privacidad/)).toBeInTheDocument();
  });

  it("activates and deactivates the assistant", async () => {
    const { calls } = setup(false, {
      [`POST ${FOLLOW}`]: { meeting_id: 1, following: true },
      [`DELETE ${FOLLOW}`]: undefined,
    });
    await userEvent.click(await screen.findByRole("button", { name: "Activar asistente" }));
    expect(await screen.findByRole("button", { name: "Desactivar asistente" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Desactivar asistente" }));
    expect(await screen.findByRole("button", { name: "Activar asistente" })).toBeInTheDocument();
    expect(calls.filter((c) => c.path === FOLLOW).map((c) => c.method)).toEqual(["POST", "DELETE"]);
  });

  it("shows a detected question and streams its answer", async () => {
    const { stream } = setup(true);
    await screen.findByRole("button", { name: "Desactivar asistente" });

    stream.send(question(1));
    expect(await screen.findByText("¿Cuándo entregáis?")).toBeInTheDocument();
    expect(screen.getByText("01:15")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Responder/ })).toBeInTheDocument();

    stream.send({ id: 2, type: "answer_start", question_id: "q1" });
    stream.send({ id: 3, type: "answer_chunk", question_id: "q1", content: "Entregamos " });
    stream.send({ id: 4, type: "answer_chunk", question_id: "q1", content: "el viernes" });
    expect(await screen.findByText("Entregamos el viernes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Responder/ })).not.toBeInTheDocument();

    stream.send({ id: 5, type: "answer_done", question_id: "q1", content: "Entregamos el viernes 20." });
    expect(await screen.findByText("Entregamos el viernes 20.")).toBeInTheDocument();
  });

  it("asks the service to answer a detected question that was not answered", async () => {
    const { stream, calls } = setup(true, { [`POST ${ANSWER}`]: {} });
    await screen.findByRole("button", { name: "Desactivar asistente" });
    stream.send(question(1));
    await userEvent.click(await screen.findByRole("button", { name: /Responder/ }));
    const answered = () => calls.some((c) => c.method === "POST" && c.path === ANSWER);
    await vi.waitFor(() => expect(answered()).toBe(true));
  });

  it("sends a manual question and clears the box", async () => {
    const { stream, calls } = setup(false, { "POST /assistant/v1/meetings/1/ask": { question_id: "q1" } });
    const input = await screen.findByPlaceholderText("Pregunta algo al asistente");
    const send = screen.getByRole("button", { name: /Preguntar/ });
    expect(send).toBeDisabled();

    await userEvent.type(input, "¿Qué riesgos hay?");
    await userEvent.click(send);

    await vi.waitFor(() => expect(input).toHaveValue(""));
    const ask = calls.find((c) => c.method === "POST" && c.path === "/assistant/v1/meetings/1/ask");
    expect(JSON.parse(ask!.init.body as string)).toEqual({ text: "¿Qué riesgos hay?" });

    stream.send(question(1, "manual"));
    expect(await screen.findByText("(tu pregunta)")).toBeInTheDocument();
    expect(screen.getByText(/Pensando/)).toBeInTheDocument();
  });

  it("shows why an answer failed", async () => {
    const { stream } = setup(true);
    await screen.findByRole("button", { name: "Desactivar asistente" });
    stream.send(question(1));
    await screen.findByText("¿Cuándo entregáis?");
    stream.send({ id: 2, type: "error", question_id: "q1", error: "leak_detected" });
    expect(await screen.findByText(/filtro de privacidad bloqueó la consulta/)).toBeInTheDocument();
  });

  it("says the assistant is not available when the service does not answer", async () => {
    mockApi({}); // todo 404
    renderApp(<AssistantPanel meetingId={1} />);
    expect(await screen.findByText("Asistente no disponible")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar asistente" })).not.toBeInTheDocument();
  });

  it("says so when the gateway fails too (container down)", async () => {
    mockApi({ [STATUS]: new Response("", { status: 502 }) });
    renderApp(<AssistantPanel meetingId={1} />);
    expect(await screen.findByText("Asistente no disponible")).toBeInTheDocument();
  });
});
