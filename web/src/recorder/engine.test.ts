import { describe, expect, it, vi } from "vitest";
import { ChunkAccumulator, encodeWav, resample, Uploader, type AudioChunk, type UploadStats } from "./engine";

// jsdom no implementa Blob.arrayBuffer(); FileReader sí.
const readBlob = (blob: Blob) =>
  new Promise<ArrayBuffer>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as ArrayBuffer);
    r.onerror = () => reject(r.error);
    r.readAsArrayBuffer(blob);
  });

async function wavInfo(blob: Blob) {
  const v = new DataView(await readBlob(blob));
  const str = (o: number, n: number) => String.fromCharCode(...Array.from({ length: n }, (_, i) => v.getUint8(o + i)));
  return {
    riff: str(0, 4),
    wave: str(8, 4),
    format: v.getUint16(20, true),
    channels: v.getUint16(22, true),
    rate: v.getUint32(24, true),
    bits: v.getUint16(34, true),
    dataBytes: v.getUint32(40, true),
    sample: (i: number) => v.getInt16(44 + i * 2, true),
  };
}

describe("resample", () => {
  it("returns the same buffer when rates match", () => {
    const x = new Float32Array([1, 2, 3]);
    expect(resample(x, 16000, 16000)).toBe(x);
  });

  it("downsamples 48k → 16k averaging each window (low-pass)", () => {
    const x = new Float32Array([0, 0.3, 0.6, 1, 1, 1, -1, -1, -1]);
    const out = resample(x, 48000, 16000);
    expect(out).toHaveLength(3);
    expect(Array.from(out)).toEqual([expect.closeTo(0.3), expect.closeTo(1), expect.closeTo(-1)]);
  });

  it("handles non-integer ratios (44.1k) with the right length", () => {
    const out = resample(new Float32Array(44100), 44100, 16000);
    expect(out.length).toBe(16000);
  });

  it("upsamples by interpolation", () => {
    const out = resample(new Float32Array([0, 1]), 8000, 16000);
    expect(out).toHaveLength(4);
    expect(out[1]).toBeCloseTo(0.5);
  });
});

describe("encodeWav", () => {
  it("writes a valid 16-bit PCM mono header", async () => {
    const info = await wavInfo(encodeWav(new Float32Array(160), 16000));
    expect(info).toMatchObject({
      riff: "RIFF",
      wave: "WAVE",
      format: 1,
      channels: 1,
      rate: 16000,
      bits: 16,
      dataBytes: 320,
    });
  });

  it("scales and clips samples", async () => {
    const info = await wavInfo(encodeWav(new Float32Array([0, 1, -1, 2, -2, 0.5]), 16000));
    expect([0, 1, 2, 3, 4].map(info.sample)).toEqual([0, 32767, -32768, 32767, -32768]);
    expect(info.sample(5)).toBe(Math.floor(0.5 * 0x7fff));
  });
});

describe("ChunkAccumulator", () => {
  const block = (n: number) => new Float32Array(n).fill(0.1);

  it("emits a chunk each time chunkSeconds of audio accumulates, with increasing seq and offsets", () => {
    const chunks: AudioChunk[] = [];
    const acc = new ChunkAccumulator("mic", 1000, (c) => chunks.push(c), 2); // 2 s a 1 kHz
    for (let i = 0; i < 9; i++) acc.push(block(500)); // 4,5 s
    expect(chunks.map((c) => [c.seq, c.offset, c.seconds])).toEqual([
      [0, 0, 2],
      [1, 2, 2],
    ]);
    expect(chunks.every((c) => c.source === "mic" && c.blob.type === "audio/wav")).toBe(true);
  });

  it("flush emits the tail only if it is long enough", () => {
    const chunks: AudioChunk[] = [];
    const acc = new ChunkAccumulator("system", 1000, (c) => chunks.push(c), 10);
    acc.push(block(300));
    acc.flush(0.5);
    expect(chunks).toHaveLength(0); // 0,3 s: se descarta
    acc.push(block(400));
    acc.flush(0.5);
    expect(chunks.map((c) => [c.seq, c.offset, c.seconds])).toEqual([[0, 0, 0.7]]);
  });

  it("encodes chunks at 16 kHz regardless of the capture rate", async () => {
    const chunks: AudioChunk[] = [];
    const acc = new ChunkAccumulator("mic", 48000, (c) => chunks.push(c), 1);
    acc.push(block(48000));
    const info = await wavInfo(chunks[0].blob);
    expect(info.rate).toBe(16000);
    expect(info.dataBytes).toBe(16000 * 2);
  });
});

vi.mock("../api", async (orig) => {
  const mod = await orig<typeof import("../api")>();
  return { ...mod, api: { ...mod.api, uploadChunk: vi.fn() } };
});

describe("Uploader", async () => {
  const { api, ApiError } = await import("../api");
  const upload = vi.mocked(api.uploadChunk);
  const chunk = (seq: number): AudioChunk => ({
    seq,
    source: "mic",
    offset: seq * 45,
    seconds: 45,
    blob: new Blob(["x"]),
  });

  it("uploads in order with the right form fields", async () => {
    upload.mockReset().mockResolvedValue({});
    const stats: UploadStats[] = [];
    const u = new Uploader(9, (s) => stats.push(s), 1);
    u.add(chunk(0));
    u.add(chunk(1));
    await u.idle();
    expect(upload).toHaveBeenCalledTimes(2);
    const [id, form] = upload.mock.calls[1];
    expect(id).toBe(9);
    expect(form.get("seq")).toBe("1");
    expect(form.get("offset_seconds")).toBe("45.000");
    expect(form.get("source")).toBe("mic");
    expect((form.get("file") as File).name).toBe("000001_mic.wav");
    expect(stats.at(-1)).toMatchObject({ sent: 2, queued: 0, failed: 0, secondsSent: 90 });
  });

  it("retries transient errors and then succeeds", async () => {
    upload
      .mockReset()
      .mockRejectedValueOnce(new ApiError(0, "red"))
      .mockRejectedValueOnce(new ApiError(503, "x"))
      .mockResolvedValue({});
    const u = new Uploader(1, () => undefined, 1);
    u.add(chunk(0));
    await u.idle();
    expect(upload).toHaveBeenCalledTimes(3);
    expect(u.stats).toMatchObject({ sent: 1, failed: 0, retrying: false });
  });

  it("does not retry client errors and counts the chunk as failed", async () => {
    upload.mockReset().mockRejectedValue(new ApiError(409, "La reunión ya no admite audio"));
    const u = new Uploader(1, () => undefined, 1);
    u.add(chunk(0));
    await u.idle();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(u.stats).toMatchObject({ sent: 0, failed: 1 });
  });

  it("gives up after 6 attempts on persistent server errors", async () => {
    upload.mockReset().mockRejectedValue(new ApiError(500, "boom"));
    const u = new Uploader(1, () => undefined, 1);
    u.add(chunk(0));
    u.add(chunk(1));
    await u.idle();
    expect(upload).toHaveBeenCalledTimes(12);
    expect(u.stats).toMatchObject({ sent: 0, failed: 2, queued: 0 });
  });

  it("idle resolves immediately when there is nothing to send", async () => {
    await expect(new Uploader(1, () => undefined).idle()).resolves.toBeUndefined();
  });
});
