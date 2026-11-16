import { describe, expect, it } from "vitest";
import { applyEvent, EMPTY_VIEW, errorText, type AssistantView } from "./assistantState";
import type { AssistantEvent } from "./types";

const q = (id: number, qid = "q1", origin: "detected" | "manual" = "detected"): AssistantEvent => ({
  id,
  type: "question",
  question_id: qid,
  text: "¿Cuándo entregáis?",
  ts: 65,
  origin,
  score: 0.8,
});

const run = (events: AssistantEvent[]): AssistantView => events.reduce(applyEvent, EMPTY_VIEW);

describe("applyEvent", () => {
  it("adds a detected question as unanswered", () => {
    const view = run([q(1)]);
    expect(view.items).toEqual([
      {
        id: "q1",
        text: "¿Cuándo entregáis?",
        ts: 65,
        origin: "detected",
        score: 0.8,
        answer: "",
        status: "unanswered",
      },
    ]);
    expect(view.lastId).toBe(1);
  });

  it("accumulates chunks while streaming and ends with the full text", () => {
    const streaming = run([
      q(1),
      { id: 2, type: "answer_start", question_id: "q1" },
      { id: 3, type: "answer_chunk", question_id: "q1", content: "El " },
      { id: 4, type: "answer_chunk", question_id: "q1", content: "viernes" },
    ]);
    expect(streaming.items[0]).toMatchObject({ status: "streaming", answer: "El viernes" });

    const done = applyEvent(streaming, { id: 5, type: "answer_done", question_id: "q1", content: "El viernes." });
    expect(done.items[0]).toMatchObject({ status: "done", answer: "El viernes." });
  });

  it("ignores events it has already applied (replays after reconnecting)", () => {
    const once = run([q(1), { id: 2, type: "answer_chunk", question_id: "q1", content: "A" }]);
    const again = applyEvent(once, { id: 2, type: "answer_chunk", question_id: "q1", content: "A" });
    expect(again).toBe(once);
    expect(again.items[0].answer).toBe("A");
  });

  it("does not duplicate a question with the same id", () => {
    expect(run([q(1), q(2)]).items).toHaveLength(1);
    expect(run([q(1), q(2, "q2")]).items).toHaveLength(2);
  });

  it("marks a question as failed with a friendly message", () => {
    const view = run([q(1), { id: 2, type: "error", question_id: "q1", error: "leak_detected" }]);
    expect(view.items[0].status).toBe("error");
    expect(view.items[0].error).toMatch(/filtro de privacidad bloqueó/);
  });

  it("keeps errors without a question as notices", () => {
    const view = run([{ id: 1, type: "error", error: "shield_unavailable" }]);
    expect(view.notices).toEqual([errorText("shield_unavailable")]);
    expect(view.items).toEqual([]);
  });

  it("explains unknown error codes without hiding them", () => {
    expect(errorText("raro")).toBe("Error del asistente (raro).");
  });

  it("leaves status events and orphan chunks harmless", () => {
    const view = run([
      { id: 1, type: "status", state: "following" },
      { id: 2, type: "answer_chunk", question_id: "no-existe", content: "x" },
    ]);
    expect(view.items).toEqual([]);
    expect(view.lastId).toBe(2);
  });
});
