import type { EventKind, Meeting } from "./types";

export function fmtTs(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.floor(seconds ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${String(m).padStart(2, "0")}:${sec}`;
}

const dateFmt = new Intl.DateTimeFormat("es-ES", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const rtf = new Intl.RelativeTimeFormat("es", { numeric: "auto" });

export function fmtDate(iso: string): string {
  return dateFmt.format(new Date(iso));
}

export function fmtRelative(iso: string): string {
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return "ahora mismo";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), "day");
  return fmtDate(iso);
}

export function fmtDuration(a: string, b: string | null): string | null {
  if (!b) return null;
  const mins = Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
  if (mins < 1) return "< 1 min";
  return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`;
}

export type Phase = "recording" | "transcribing" | "analyzing" | "ready" | "failed";

export function phaseOf(m: Meeting): Phase {
  if (m.status === "recording") return "recording";
  if (m.status === "finished") return "transcribing";
  if (m.analysis_status === "pending") return "analyzing";
  if (m.analysis_status === "failed") return "failed";
  return "ready";
}

export const PHASE_LABEL: Record<Phase, string> = {
  recording: "Grabando",
  transcribing: "Transcribiendo",
  analyzing: "Analizando con IA",
  ready: "Lista",
  failed: "Análisis fallido",
};

export const isBusy = (p: Phase) => p === "transcribing" || p === "analyzing";

export const KIND: Record<EventKind, { label: string; plural: string; tone: string }> = {
  new_requirement: { label: "Requisito nuevo", plural: "Requisitos nuevos", tone: "green" },
  changed_requirement: { label: "Cambio", plural: "Cambios de requisitos", tone: "amber" },
  decision: { label: "Decisión", plural: "Decisiones", tone: "violet" },
  open_question: { label: "Duda abierta", plural: "Dudas abiertas", tone: "sky" },
};

export const SPEAKER: Record<string, string> = { mic: "Yo", system: "Otros", mix: "Audio" };

export function meetingTitle(m: Pick<Meeting, "id" | "title">): string {
  return m.title.trim() || `Reunión #${m.id}`;
}

export function downloadText(filename: string, text: string, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(s: string): string {
  return (
    s
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "reunion"
  );
}
