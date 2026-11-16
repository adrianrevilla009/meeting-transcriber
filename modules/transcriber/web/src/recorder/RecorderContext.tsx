import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { assistant } from "../assistantApi";
import type { Meeting } from "../types";
import {
  CHUNK_SECONDS,
  LIVE_CHUNK_SECONDS,
  SourceCapture,
  Uploader,
  workletModuleUrl,
  type UploadStats,
} from "./engine";

export type RecorderPhase = "idle" | "starting" | "recording" | "stopping";

export interface StartOptions {
  title: string;
  project: string;
  mic: boolean;
  system: boolean;
  /** Asistente en vivo: trozos cortos y seguimiento de la reunión por el módulo 3. */
  assistant?: boolean;
}

interface RecorderState {
  phase: RecorderPhase;
  meeting: Meeting | null;
  startedAt: number | null;
  chunkSeconds: number;
  assistant: boolean;
  analysers: { mic?: AnalyserNode; system?: AnalyserNode };
  stats: UploadStats;
  warnings: string[];
  error: string | null;
}

interface RecorderApi extends RecorderState {
  start: (o: StartOptions) => Promise<void>;
  stop: () => Promise<number | null>;
  dismissError: () => void;
}

const EMPTY_STATS: UploadStats = { sent: 0, queued: 0, failed: 0, retrying: false, secondsSent: 0 };
const INITIAL: RecorderState = {
  phase: "idle",
  meeting: null,
  startedAt: null,
  chunkSeconds: CHUNK_SECONDS,
  assistant: false,
  analysers: {},
  stats: EMPTY_STATS,
  warnings: [],
  error: null,
};

const Ctx = createContext<RecorderApi | null>(null);

function describeMediaError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError") return "Permiso denegado. Permite el acceso al micrófono / pantalla para grabar.";
  if (name === "NotFoundError") return "No se encontró ningún micrófono.";
  if (name === "NotReadableError") return "El micrófono está en uso por otra aplicación.";
  return e instanceof Error ? e.message : "No se pudo iniciar la grabación.";
}

export function RecorderProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<RecorderState>(INITIAL);
  const rt = useRef<{ ctx?: AudioContext; streams: MediaStream[]; captures: SourceCapture[]; uploader?: Uploader }>({
    streams: [],
    captures: [],
  });

  const patch = (p: Partial<RecorderState>) => setState((s) => ({ ...s, ...p }));
  const warn = (w: string) => setState((s) => ({ ...s, warnings: [...s.warnings, w] }));

  const teardown = () => {
    rt.current.streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
    void rt.current.ctx?.close().catch(() => undefined);
    rt.current = { streams: [], captures: [] };
  };

  const start = useCallback(async (o: StartOptions) => {
    setState({ ...INITIAL, phase: "starting" });
    let meeting: Meeting | null = null;
    try {
      const streams: { mic?: MediaStream; system?: MediaStream } = {};
      if (o.mic) {
        streams.mic = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        rt.current.streams.push(streams.mic);
      }
      if (o.system) {
        try {
          const display = await navigator.mediaDevices.getDisplayMedia({
            video: true,
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
            systemAudio: "include",
            selfBrowserSurface: "exclude",
          } as unknown as DisplayMediaStreamOptions);
          rt.current.streams.push(display);
          const tracks = display.getAudioTracks();
          if (tracks.length) {
            streams.system = new MediaStream(tracks);
            tracks[0].addEventListener("ended", () =>
              warn("Se dejó de compartir la pantalla: el audio de los demás ya no se está grabando."),
            );
          } else {
            warn('No se compartió el audio del sistema. Marca "Compartir audio del sistema" al elegir la pantalla.');
          }
        } catch (e) {
          if (!streams.mic) throw e;
          warn("No se compartió la pantalla: solo se graba tu micrófono.");
        }
      }
      if (!streams.mic && !streams.system) throw new Error("No hay ninguna fuente de audio activa.");

      meeting = await api.createMeeting(o.title.trim(), o.project.trim());
      const ctx = new AudioContext();
      rt.current.ctx = ctx;
      await ctx.audioWorklet.addModule(workletModuleUrl());
      await ctx.resume();

      const chunkSeconds = o.assistant ? LIVE_CHUNK_SECONDS : CHUNK_SECONDS;
      const uploader = new Uploader(meeting.id, (stats) => patch({ stats: { ...stats } }));
      rt.current.uploader = uploader;
      const analysers: RecorderState["analysers"] = {};
      for (const source of ["mic", "system"] as const) {
        const stream = streams[source];
        if (!stream) continue;
        const cap = new SourceCapture(ctx, stream, source, (c) => uploader.add(c), chunkSeconds);
        rt.current.captures.push(cap);
        analysers[source] = cap.analyser;
      }
      let following = false;
      if (o.assistant) {
        try {
          await assistant.follow(meeting.id);
          following = true;
        } catch {
          warn("No se pudo activar el asistente en vivo. Puedes activarlo desde la reunión.");
        }
      }
      patch({ phase: "recording", meeting, startedAt: Date.now(), analysers, chunkSeconds, assistant: following });
    } catch (e) {
      teardown();
      if (meeting) void api.deleteMeeting(meeting.id).catch(() => undefined);
      setState((s) => ({ ...INITIAL, warnings: s.warnings, error: describeMediaError(e) }));
    }
  }, []);

  const stop = useCallback(async () => {
    const { captures, uploader } = rt.current;
    const meeting = state.meeting;
    if (!meeting) return null;
    patch({ phase: "stopping" });
    await Promise.all(captures.map((c) => c.stop()));
    teardown();
    await uploader?.idle();
    for (let i = 0; i < 5; i++) {
      try {
        await api.finish(meeting.id);
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
      }
    }
    setState(INITIAL);
    return meeting.id;
  }, [state.meeting]);

  // Evita cerrar la pestaña a mitad de una grabación.
  useEffect(() => {
    if (state.phase !== "recording" && state.phase !== "stopping") return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [state.phase]);

  const dismissError = useCallback(() => patch({ error: null, warnings: [] }), []);

  return <Ctx.Provider value={{ ...state, start, stop, dismissError }}>{children}</Ctx.Provider>;
}

export function useRecorder(): RecorderApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useRecorder fuera de RecorderProvider");
  return v;
}

export function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [startedAt]);
  return startedAt ? Math.max(0, (now - startedAt) / 1000) : 0;
}
