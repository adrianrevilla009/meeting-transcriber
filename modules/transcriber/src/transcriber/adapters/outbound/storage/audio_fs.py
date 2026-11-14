"""Adaptador de almacenamiento de audio en disco local."""

import re
from pathlib import Path

from transcriber.config import get_settings

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]")


class FsAudioStore:
    def path_for(self, meeting_id: int, seq: int, source: str, suffix: str) -> Path:
        safe_suffix = _SAFE.sub("", suffix) or ".wav"
        d = get_settings().audio_dir / f"meeting_{meeting_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{seq:06d}_{_SAFE.sub('', source)}{safe_suffix}"

    def delete(self, path: str | None) -> None:
        if not path:
            return
        p = Path(path)
        try:
            p.unlink(missing_ok=True)
            # Borra la carpeta de la reunión si queda vacía.
            if p.parent.exists() and not any(p.parent.iterdir()):
                p.parent.rmdir()
        except OSError:
            pass
