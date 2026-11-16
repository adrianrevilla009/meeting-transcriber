import type { AssistantEvent } from "./types";

export type QAStatus = "unanswered" | "streaming" | "done" | "error";

export interface QA {
  id: string;
  text: string;
  ts: number;
  origin: "detected" | "manual";
  score: number;
  answer: string;
  status: QAStatus;
  error?: string;
}

export interface AssistantView {
  items: QA[];
  /** Id del último evento aplicado: los repetidos (p. ej. tras reconectar) se ignoran. */
  lastId: number;
  /** Errores que no pertenecen a una pregunta concreta. */
  notices: string[];
}

export const EMPTY_VIEW: AssistantView = { items: [], lastId: 0, notices: [] };

const ERROR_TEXT: Record<string, string> = {
  leak_detected: "El filtro de privacidad bloqueó la consulta por seguridad.",
  policy_blocked: "El filtro de privacidad bloqueó la consulta (contiene datos que no pueden salir).",
  provider_error: "El proveedor de IA falló. Inténtalo de nuevo.",
  shield_unavailable: "El filtro de privacidad no está disponible: no se envió nada.",
  detector_unavailable: "El detector de datos personales no está disponible: no se envió nada.",
  provider_not_configured: "El proveedor de IA no está configurado.",
};

export const errorText = (code: string) => ERROR_TEXT[code] ?? `Error del asistente (${code}).`;

function update(items: QA[], id: string, change: (q: QA) => QA): QA[] {
  return items.map((q) => (q.id === id ? change(q) : q));
}

/** Aplica un evento del servidor. Es pura: mismo estado + mismo evento = mismo resultado. */
export function applyEvent(view: AssistantView, e: AssistantEvent): AssistantView {
  if (e.id <= view.lastId) return view;
  const next = { ...view, lastId: e.id };
  switch (e.type) {
    case "question":
      if (view.items.some((q) => q.id === e.question_id)) return next;
      return {
        ...next,
        items: [
          ...view.items,
          {
            id: e.question_id,
            text: e.text,
            ts: e.ts,
            origin: e.origin,
            score: e.score,
            answer: "",
            status: "unanswered",
          },
        ],
      };
    case "answer_start":
      return {
        ...next,
        items: update(view.items, e.question_id, (q) => ({ ...q, answer: "", status: "streaming" })),
      };
    case "answer_chunk":
      return {
        ...next,
        items: update(view.items, e.question_id, (q) => ({ ...q, answer: q.answer + e.content, status: "streaming" })),
      };
    case "answer_done":
      return {
        ...next,
        items: update(view.items, e.question_id, (q) => ({ ...q, answer: e.content, status: "done" })),
      };
    case "error": {
      if (e.question_id && view.items.some((q) => q.id === e.question_id)) {
        return {
          ...next,
          items: update(view.items, e.question_id, (q) => ({ ...q, status: "error", error: errorText(e.error) })),
        };
      }
      return { ...next, notices: [...view.notices, errorText(e.error)] };
    }
    default:
      return next;
  }
}
