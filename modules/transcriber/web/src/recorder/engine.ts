/**
 * Captura en el navegador, equivalente a agent/capture_agent.py:
 * cada fuente (micrófono / audio del sistema) se graba por separado, se corta en trozos de
 * CHUNK_SECONDS, se pasa a WAV mono 16 kHz y se sube a la API con reintentos.
 * Los offsets se calculan por muestras, no por reloj, para que no deriven.
 */
import { api, ApiError } from "../api";

export type Source = "mic" | "system";
export const CHUNK_SECONDS = 45;
/** Trozos cortos para el asistente en vivo: la respuesta llega antes, a costa de algo de precisión. */
export const LIVE_CHUNK_SECONDS = 12;
const TARGET_SR = 16_000;

export interface AudioChunk {
  seq: number;
  source: Source;
  offset: number;
  seconds: number;
  blob: Blob;
}

// Worklet: mezcla a mono y envía bloques al hilo principal. Si la fuente se corta, emite
// silencio para que la línea temporal siga avanzando.
const WORKLET_SRC = `
class MtTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.parts = [];
    this.n = 0;
    this.port.onmessage = () => this.flush(true);
  }
  flush(final) {
    const all = new Float32Array(this.n);
    let o = 0;
    for (const p of this.parts) { all.set(p, o); o += p.length; }
    this.parts = [];
    this.n = 0;
    this.port.postMessage({ data: all, final }, [all.buffer]);
  }
  process(inputs) {
    const input = inputs[0];
    const len = input && input.length ? input[0].length : 128;
    const out = new Float32Array(len);
    if (input && input.length) {
      for (const ch of input) for (let i = 0; i < len; i++) out[i] += ch[i] / input.length;
    }
    this.parts.push(out);
    this.n += len;
    if (this.n >= 16384) this.flush(false);
    return true;
  }
}
registerProcessor("mt-tap", MtTap);
`;

let workletUrl: string | null = null;
export function workletModuleUrl(): string {
  workletUrl ??= URL.createObjectURL(new Blob([WORKLET_SRC], { type: "application/javascript" }));
  return workletUrl;
}

/** Diezmado con media por ventana (filtro paso bajo simple) o interpolación si sube la tasa. */
export function resample(x: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return x;
  const ratio = from / to;
  const n = Math.floor(x.length / ratio);
  const out = new Float32Array(n);
  if (ratio > 1) {
    for (let i = 0; i < n; i++) {
      const s = Math.floor(i * ratio);
      const e = Math.min(x.length, Math.max(s + 1, Math.floor((i + 1) * ratio)));
      let sum = 0;
      for (let k = s; k < e; k++) sum += x[k];
      out[i] = sum / (e - s);
    }
  } else {
    for (let i = 0; i < n; i++) {
      const p = i * ratio;
      const j = Math.floor(p);
      const a = x[j];
      const b = x[Math.min(j + 1, x.length - 1)];
      out[i] = a + (b - a) * (p - j);
    }
  }
  return out;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/**
 * Acumula muestras de una fuente y emite trozos de `chunkSeconds` como WAV 16 kHz.
 * Sin dependencias de Web Audio: es la parte que decide seq, offsets y cortes.
 */
export class ChunkAccumulator {
  private parts: Float32Array[] = [];
  private partLen = 0;
  private chunkStart = 0;
  private seq = 0;

  constructor(
    readonly source: Source,
    private sampleRate: number,
    private onChunk: (c: AudioChunk) => void,
    private chunkSeconds = CHUNK_SECONDS,
  ) {}

  push(d: Float32Array) {
    this.parts.push(d);
    this.partLen += d.length;
    if (this.partLen >= this.chunkSeconds * this.sampleRate) this.emit();
  }

  /** Emite lo pendiente si dura al menos `minSeconds` (descarta colas de silencio de milisegundos). */
  flush(minSeconds = 0.5) {
    if (this.partLen >= minSeconds * this.sampleRate) this.emit();
  }

  private emit() {
    if (!this.partLen) return;
    const all = new Float32Array(this.partLen);
    let o = 0;
    for (const p of this.parts) {
      all.set(p, o);
      o += p.length;
    }
    this.onChunk({
      seq: this.seq++,
      source: this.source,
      offset: this.chunkStart / this.sampleRate,
      seconds: all.length / this.sampleRate,
      blob: encodeWav(resample(all, this.sampleRate, TARGET_SR), TARGET_SR),
    });
    this.chunkStart += all.length;
    this.parts = [];
    this.partLen = 0;
  }
}

export class SourceCapture {
  readonly analyser: AnalyserNode;
  private src: MediaStreamAudioSourceNode;
  private node: AudioWorkletNode;
  private sink: GainNode;
  private acc: ChunkAccumulator;
  private onFinal: (() => void) | null = null;

  constructor(
    ctx: AudioContext,
    stream: MediaStream,
    readonly source: Source,
    onChunk: (c: AudioChunk) => void,
    chunkSeconds = CHUNK_SECONDS,
  ) {
    this.acc = new ChunkAccumulator(source, ctx.sampleRate, onChunk, chunkSeconds);
    this.src = ctx.createMediaStreamSource(stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.75;
    this.node = new AudioWorkletNode(ctx, "mt-tap", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
    this.sink = ctx.createGain();
    this.sink.gain.value = 0; // el worklet necesita estar conectado al destino, pero sin sonar
    this.src.connect(this.analyser);
    this.src.connect(this.node);
    this.node.connect(this.sink).connect(ctx.destination);
    this.node.port.onmessage = (e: MessageEvent<{ data: Float32Array; final: boolean }>) => {
      if (e.data.data.length) this.acc.push(e.data.data);
      if (e.data.final) this.onFinal?.();
    };
  }

  async stop() {
    await new Promise<void>((resolve) => {
      this.onFinal = resolve;
      this.node.port.postMessage("flush");
      setTimeout(resolve, 1500);
    });
    this.acc.flush();
    this.src.disconnect();
    this.node.disconnect();
    this.sink.disconnect();
  }
}

export interface UploadStats {
  sent: number;
  queued: number;
  failed: number;
  retrying: boolean;
  secondsSent: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class Uploader {
  private queue: AudioChunk[] = [];
  private busy = false;
  private waiters: (() => void)[] = [];
  stats: UploadStats = { sent: 0, queued: 0, failed: 0, retrying: false, secondsSent: 0 };

  constructor(
    private meetingId: number,
    private onStats: (s: UploadStats) => void,
    private retryBaseMs = 1000,
  ) {}

  add(c: AudioChunk) {
    this.queue.push(c);
    this.update({ queued: this.stats.queued + 1 });
    void this.pump();
  }

  private update(patch: Partial<UploadStats>) {
    this.stats = { ...this.stats, ...patch };
    this.onStats(this.stats);
  }

  private async pump() {
    if (this.busy) return;
    this.busy = true;
    while (this.queue.length) {
      const c = this.queue[0];
      let ok = false;
      for (let attempt = 1; attempt <= 6 && !ok; attempt++) {
        try {
          const form = new FormData();
          form.append(
            "file",
            new File([c.blob], `${String(c.seq).padStart(6, "0")}_${c.source}.wav`, { type: "audio/wav" }),
          );
          form.append("seq", String(c.seq));
          form.append("offset_seconds", c.offset.toFixed(3));
          form.append("source", c.source);
          await api.uploadChunk(this.meetingId, form);
          ok = true;
        } catch (e) {
          // 4xx (salvo timeouts/limitación) no se arregla reintentando.
          if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![408, 429].includes(e.status)) break;
          this.update({ retrying: true });
          await sleep(Math.min(this.retryBaseMs * 2 ** attempt, 15 * this.retryBaseMs));
        }
      }
      this.queue.shift();
      this.update({
        queued: this.stats.queued - 1,
        sent: this.stats.sent + (ok ? 1 : 0),
        failed: this.stats.failed + (ok ? 0 : 1),
        secondsSent: this.stats.secondsSent + (ok ? c.seconds : 0),
        retrying: false,
      });
    }
    this.busy = false;
    this.waiters.splice(0).forEach((w) => w());
  }

  idle(): Promise<void> {
    if (!this.busy && !this.queue.length) return Promise.resolve();
    return new Promise((r) => this.waiters.push(r));
  }
}
