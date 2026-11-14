"""Agente de captura para Windows (micrófono + audio del sistema).

Graba ambos orígenes a 16 kHz mono, los corta en trozos y los sube a la API.
Si la API no responde, los trozos se guardan en una carpeta de spool y se reintentan.

Uso:
    python capture_agent.py --api http://127.0.0.1:8000 --token TOKEN --title "Kickoff" --project pagos
Ctrl+C termina la reunión y avisa a la API.
"""

import argparse
import queue
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
import requests
import soundfile as sf

TARGET_SR = 16_000


def to_mono_16k(raw: bytes, channels: int, rate: int) -> np.ndarray:
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != TARGET_SR:
        n = int(len(x) * TARGET_SR / rate)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


class Uploader(threading.Thread):
    def __init__(self, api: str, token: str, meeting_id: int, spool: Path):
        super().__init__(daemon=True)
        self.api, self.meeting_id, self.spool = api.rstrip("/"), meeting_id, spool
        self.headers = {"Authorization": f"Bearer {token}"}
        self.q: queue.Queue = queue.Queue()
        self.running = True

    def submit(self, seq: int, offset: float, source: str, audio: np.ndarray) -> None:
        path = self.spool / f"{seq:06d}_{source}.wav"
        sf.write(path, audio, TARGET_SR, subtype="PCM_16")
        self.q.put((seq, offset, source, path))

    def run(self) -> None:
        while self.running or not self.q.empty():
            try:
                seq, offset, source, path = self.q.get(timeout=1)
            except queue.Empty:
                continue
            for attempt in range(1, 6):
                try:
                    with open(path, "rb") as fh:
                        r = requests.post(
                            f"{self.api}/meetings/{self.meeting_id}/chunks",
                            headers=self.headers,
                            files={"file": (path.name, fh, "audio/wav")},
                            data={"seq": seq, "offset_seconds": offset, "source": source},
                            timeout=60,
                        )
                    r.raise_for_status()
                    path.unlink(missing_ok=True)  # subido: no dejamos audio en local
                    break
                except requests.RequestException as exc:
                    print(f"[uploader] intento {attempt} fallido ({exc}); el trozo queda en {path}")
                    time.sleep(min(2**attempt, 30))


def record_stream(pa, device, source: str, chunk_s: int, start: float, uploader: Uploader, stop: threading.Event):
    rate, channels = int(device["defaultSampleRate"]), device["maxInputChannels"]
    frames_per_buffer = 1024
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=device["index"],
        frames_per_buffer=frames_per_buffer,
    )
    buf, seq = [], 0
    chunk_start = time.monotonic() - start
    try:
        while not stop.is_set():
            buf.append(stream.read(frames_per_buffer, exception_on_overflow=False))
            if len(buf) * frames_per_buffer / rate >= chunk_s:
                uploader.submit(seq, chunk_start, source, to_mono_16k(b"".join(buf), channels, rate))
                seq += 1
                chunk_start = time.monotonic() - start
                buf = []
        if buf:
            uploader.submit(seq, chunk_start, source, to_mono_16k(b"".join(buf), channels, rate))
    finally:
        stream.stop_stream()
        stream.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--token", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--project", default="")
    ap.add_argument("--chunk-seconds", type=int, default=45)
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--no-system", action="store_true")
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"}
    r = requests.post(
        f"{args.api}/meetings", headers=headers, json={"title": args.title, "project": args.project}, timeout=15
    )
    r.raise_for_status()
    meeting_id = r.json()["id"]
    print(f"Reunión {meeting_id} iniciada. Ctrl+C para terminar.")

    spool = Path(tempfile.mkdtemp(prefix="mt_spool_"))
    uploader = Uploader(args.api, args.token, meeting_id, spool)
    uploader.start()

    pa = pyaudio.PyAudio()
    stop = threading.Event()
    t0 = time.monotonic()
    threads = []
    if not args.no_mic:
        mic = pa.get_default_input_device_info()
        threads.append(
            threading.Thread(target=record_stream, args=(pa, mic, "mic", args.chunk_seconds, 0.0, uploader, stop))
        )
    if not args.no_system:
        loop = pa.get_default_wasapi_loopback()  # lo que suena por los altavoces/auriculares
        threads.append(
            threading.Thread(target=record_stream, args=(pa, loop, "system", args.chunk_seconds, 0.0, uploader, stop))
        )
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nTerminando...")
    stop.set()
    for t in threads:
        t.join()
    uploader.running = False
    uploader.join()
    requests.post(f"{args.api}/meetings/{meeting_id}/finish", headers=headers, timeout=15).raise_for_status()
    pa.terminate()
    print(f"Hecho ({time.monotonic() - t0:.0f} s). Transcripción: GET /meetings/{meeting_id}/transcript")


if __name__ == "__main__":
    main()
