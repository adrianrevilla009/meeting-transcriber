from pathlib import Path

from transcriber.domain.transcription import RawSegment


class FakeTranscriber:
    """Para tests y desarrollo sin modelo: devuelve el contenido del audio como texto si es .txt,
    o un segmento fijo."""

    def transcribe(self, path: Path) -> list[RawSegment]:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (UnicodeDecodeError, OSError):
            text = "texto de prueba"
        out, t = [], 0.0
        for line in [ln for ln in text.splitlines() if ln.strip()]:
            lp = -0.2
            if line.startswith("?"):
                line, lp = line[1:].strip(), -1.5
            out.append(RawSegment(t, t + 5.0, line, lp, 0.01))
            t += 5.0
        return out
